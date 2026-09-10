import { Component, computed, ElementRef, inject, signal } from '@angular/core';
import { CurrencyPipe, DecimalPipe } from '@angular/common';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';
import { catchError, of, switchMap, timer } from 'rxjs';

import { InvestmentApiService } from '../../core/services/investment-api.service';
import { MarketPriceApiService } from '../../core/services/market-price-api.service';
import { PeriodStorageService } from '../../core/services/period-storage.service';
import {
  AssetInvestmentDetail,
  AssetType,
  CategoryDetailResponse,
  CategoryOverview,
  InvestmentOverviewResponse,
} from '../../core/models/investment.model';
import { MarketPriceResponse } from '../../core/models/market-price.model';
import { AssetEditDialogComponent } from './components/asset-edit-dialog/asset-edit-dialog.component';
import { MONTH_NAMES } from '../../core/models/month-names';
import { EurCurrencyPipe } from '../../core/pipes/eur-currency.pipe';
import { DonutSegment, SegmentDonutChartComponent } from '../../shared/components/segment-donut-chart/segment-donut-chart.component';
import { parseDecimalInput } from '../../core/utils/parse-decimal';
import { readCssVar } from '../../core/utils/read-css-var';

/** Sondeo de precios en vivo: cada 35s, arranca al montar el componente. */
const MARKET_PRICE_POLL_MS = 35_000;

/** Métricas derivadas del precio en vivo (valor de mercado y P/L vs importe registrado). */
interface LivePriceMetrics {
  price: number;
  currency: string;
  showEurToggle: boolean;
  marketValue: number | null;
  profit: number | null;
  profitPct: number | null;
}

/** Resumen agregado de P/L en vivo de una categoría (siempre en EUR). */
interface CategoryLiveSummary {
  profitEur: number;
  profitPct: number;
  assetCount: number;
  hasData: boolean;
}

const FALLBACK_DEFAULTS = ['#f59e0b', '#6366f1', '#22c55e', '#ec4899', '#06b6d4', '#eab308', '#f43f5e'];

/** Convierte un número a texto para prellenar inputs; nunca se usa mientras el usuario escribe,
 * así que no interfiere con la coma/punto que esté tecleando en ese momento. */
function toInputString(value: number | null | undefined): string {
  return value === null || value === undefined ? '' : String(value);
}

interface AssetRow {
  assetTypeId: string;
  name: string;
  ticker: string | null;
  currency: string;
  amount: string;
  units: string;
  monthlyContribution: number | null;
  hasTransactions: boolean;
}

interface AssetEditSnapshotRow {
  assetTypeId: string;
  amount: string;
  units: string;
}

interface AssetEditSnapshot {
  assetRows: AssetEditSnapshotRow[];
  categoryTotalInput: string;
}

interface CategoryPanelState {
  open: boolean;
  loadingDetail: boolean;
  detail: CategoryDetailResponse | null;
  errorMessage: string | null;
  assetEditMode: boolean;
  assetRows: AssetRow[];
  fxUsdToEur: number | null;
  savingAssets: boolean;
  showAddAsset: boolean;
  newAssetName: string;
  newAssetTicker: string;
  newAssetCurrency: string;
  creatingAsset: boolean;
  /** Total de categoría editable en modo edición (EUR). */
  categoryTotalInput: string;
  /** Estado al entrar en edición; sirve para detectar cambios pendientes. */
  editSnapshot: AssetEditSnapshot | null;
}

function createPanelState(): CategoryPanelState {
  return {
    open: false,
    loadingDetail: false,
    detail: null,
    errorMessage: null,
    assetEditMode: false,
    assetRows: [],
    fxUsdToEur: null,
    savingAssets: false,
    showAddAsset: false,
    newAssetName: '',
    newAssetTicker: '',
    newAssetCurrency: 'EUR',
    creatingAsset: false,
    categoryTotalInput: '',
    editSnapshot: null,
  };
}

@Component({
  selector: 'app-investment-detail',
  imports: [CurrencyPipe, DecimalPipe, EurCurrencyPipe, SegmentDonutChartComponent, AssetEditDialogComponent],
  templateUrl: './investment-detail.component.html',
  styleUrl: './investment-detail.component.scss',
})
export class InvestmentDetailComponent {
  private readonly api = inject(InvestmentApiService);
  private readonly marketPriceApi = inject(MarketPriceApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly periodStorage = inject(PeriodStorageService);
  private readonly host = inject(ElementRef<HTMLElement>);

  readonly monthNames = MONTH_NAMES;

  private readonly storedPeriod = this.periodStorage.read();
  readonly year = signal<number>(this.storedPeriod.year);
  readonly month = signal<number>(this.storedPeriod.month);

  readonly loading = signal<boolean>(false);
  readonly errorMessage = signal<string | null>(null);

  readonly overview = signal<InvestmentOverviewResponse | null>(null);
  readonly panels = signal<Record<string, CategoryPanelState>>({});

  readonly assetEditDialogOpen = signal(false);
  readonly assetEditCategoryId = signal<string | null>(null);
  readonly assetEditTarget = signal<AssetInvestmentDetail | null>(null);
  /** Clave `${categoryId}:${assetTypeId}` mientras se recalcula desde asset_transactions. */
  readonly transactionReloadLoading = signal<Record<string, boolean>>({});

  /** Precios de mercado en vivo (GET /api/v1/market-prices), indexados por asset_type_id. */
  readonly marketPrices = signal<Record<string, MarketPriceResponse>>({});

  /** Por activo: si true, precio/valor/P/L se muestran convertidos a EUR (USD/USDT). */
  readonly livePriceEurMode = signal<Record<string, boolean>>({});

  /** Panel de info de P/L agregado abierto por categoría. */
  readonly categoryProfitInfoOpen = signal<Record<string, boolean>>({});

  readonly monthLabel = computed(() => `${this.monthNames[this.month() - 1]} ${this.year()}`);

  readonly categorySegments = computed<DonutSegment[]>(() => {
    const ov = this.overview();
    if (!ov) return [];
    return ov.categories.map((c, i) => ({
      id: c.category_id,
      label: c.name,
      value: c.amount_eur,
      color: c.color ?? this.fallbackColor(i),
    }));
  });

  constructor() {
    this.route.queryParamMap.subscribe((params) => {
      const yearParam = params.get('year');
      const monthParam = params.get('month');

      const stored = this.periodStorage.read();
      const year = yearParam ? Number(yearParam) : stored.year;
      const month = monthParam ? Number(monthParam) : stored.month;

      const monthChanged = year !== this.year() || month !== this.month();
      this.year.set(year);
      this.month.set(month);
      this.periodStorage.save(year, month);

      if (monthChanged || !this.overview()) {
        this.panels.set({});
        this.loadOverview();
      }
    });

    // Sondeo de precios en vivo: arranca al montar el componente y se cancela solo al destruirlo.
    timer(0, MARKET_PRICE_POLL_MS)
      .pipe(
        switchMap(() =>
          this.marketPriceApi.getMarketPrices().pipe(catchError(() => of<MarketPriceResponse[]>([]))),
        ),
        takeUntilDestroyed(),
      )
      .subscribe((prices) => this.applyMarketPrices(prices));
  }

  /** Fuerza una consulta inmediata (p. ej. tras editar ticker o price_source). */
  refreshMarketPrices(forceRefresh = false): void {
    this.marketPriceApi
      .getMarketPrices(forceRefresh)
      .pipe(catchError(() => of<MarketPriceResponse[]>([])))
      .subscribe((prices) => this.applyMarketPrices(prices));
  }

  private applyMarketPrices(prices: MarketPriceResponse[]): void {
    const byAssetTypeId: Record<string, MarketPriceResponse> = {};
    for (const price of prices) {
      byAssetTypeId[price.asset_type_id] = price;
    }
    this.marketPrices.set(byAssetTypeId);
  }

  /** Precio de mercado en vivo del activo, o `null` si no tiene ticker/price_source configurados. */
  livePriceFor(assetTypeId: string): MarketPriceResponse | null {
    return this.marketPrices()[assetTypeId] ?? null;
  }

  toggleLivePriceEur(assetTypeId: string): void {
    this.livePriceEurMode.update((current) => ({
      ...current,
      [assetTypeId]: !(current[assetTypeId] ?? false),
    }));
  }

  isLivePriceEurMode(assetTypeId: string): boolean {
    return this.livePriceEurMode()[assetTypeId] ?? false;
  }

  /** USDT se trata como USD en visualización y conversiones. */
  displayCurrencyCode(currency: string): string {
    return currency === 'USDT' ? 'USD' : currency;
  }

  isUsdLikeCurrency(currency: string): boolean {
    return currency === 'USD' || currency === 'USDT';
  }

  liveCurrencyToggleLabel(assetTypeId: string): string {
    return this.isLivePriceEurMode(assetTypeId) ? '€' : '$';
  }

  liveCurrencyToggleTitle(assetTypeId: string): string {
    return this.isLivePriceEurMode(assetTypeId)
      ? 'Mostrando en euros. Pulsa para ver en dólares'
      : 'Mostrando en dólares. Pulsa para ver en euros';
  }

  liveMetricsForAsset(asset: AssetInvestmentDetail, categoryId: string): LivePriceMetrics | null {
    return this.buildLiveMetrics(
      asset.asset_type_id,
      categoryId,
      asset.units,
      asset.amount_eur,
      asset.amount,
      asset.currency,
    );
  }

  liveMetricsForRow(row: AssetRow, categoryId: string): LivePriceMetrics | null {
    return this.buildLiveMetrics(
      row.assetTypeId,
      categoryId,
      parseDecimalInput(row.units),
      this.assetRowPreviewEur(categoryId, row),
      parseDecimalInput(row.amount) ?? 0,
      row.currency,
    );
  }

  liveProfitClass(profit: number | null): string {
    if (profit === null || profit === 0) {
      return 'live-price-profit live-price-profit--neutral';
    }
    return profit > 0
      ? 'live-price-profit live-price-profit--gain'
      : 'live-price-profit live-price-profit--loss';
  }

  /** Muestra el botón €/$ en activos USD o con precio en vivo USD/USDT. */
  assetShowEurToggle(asset: AssetInvestmentDetail): boolean {
    if (asset.currency === 'USD') {
      return true;
    }
    const live = this.livePriceFor(asset.asset_type_id);
    return live !== null && this.isUsdLikeCurrency(live.currency);
  }

  /** Importe invertido en la divisa activa (nativa o EUR si el toggle € está activo). */
  importeDisplayForAsset(
    asset: AssetInvestmentDetail,
  ): { amount: number; currency: string } {
    if (this.isLivePriceEurMode(asset.asset_type_id) && this.assetShowEurToggle(asset)) {
      return { amount: asset.amount_eur, currency: 'EUR' };
    }
    return { amount: asset.amount, currency: asset.currency };
  }

  toggleCategoryProfitInfo(event: Event, categoryId: string): void {
    event.stopPropagation();
    const willOpen = !(this.categoryProfitInfoOpen()[categoryId] ?? false);
    this.categoryProfitInfoOpen.update((current) => ({
      ...current,
      [categoryId]: willOpen,
    }));
    if (willOpen && !this.panel(categoryId).detail) {
      this.loadCategoryDetail(categoryId);
    }
  }

  isCategoryProfitInfoOpen(categoryId: string): boolean {
    return this.categoryProfitInfoOpen()[categoryId] ?? false;
  }

  /** Suma de ganancias/pérdidas en EUR y % agregado de los activos con precio en vivo y títulos. */
  categoryLiveSummary(categoryId: string): CategoryLiveSummary {
    const detail = this.panel(categoryId).detail;
    if (!detail) {
      return { profitEur: 0, profitPct: 0, assetCount: 0, hasData: false };
    }

    let totalProfitEur = 0;
    let totalCostEur = 0;
    let assetCount = 0;

    for (const asset of detail.assets) {
      const profitEur = this.assetProfitEur(asset, categoryId);
      if (profitEur === null) {
        continue;
      }
      totalProfitEur += profitEur;
      totalCostEur += asset.amount_eur;
      assetCount += 1;
    }

    if (assetCount === 0) {
      return { profitEur: 0, profitPct: 0, assetCount: 0, hasData: false };
    }

    const profitEur = this.round2(totalProfitEur);
    const profitPct = totalCostEur > 0 ? this.round2((profitEur / totalCostEur) * 100) : 0;
    return { profitEur, profitPct, assetCount, hasData: true };
  }

  /** P/L de un activo siempre normalizado a EUR (para agregados de categoría). */
  private assetProfitEur(asset: AssetInvestmentDetail, categoryId: string): number | null {
    const live = this.livePriceFor(asset.asset_type_id);
    const units = asset.units;
    if (!live || units === null || units <= 0) {
      return null;
    }

    const fx = this.panel(categoryId).fxUsdToEur ?? 1;
    const marketEur = this.round2(units * this.amountToEur(live.price, live.currency, fx));
    return this.round2(marketEur - asset.amount_eur);
  }

  private buildLiveMetrics(
    assetTypeId: string,
    categoryId: string,
    units: number | null | undefined,
    costEur: number,
    costNative: number,
    assetCurrency: string,
  ): LivePriceMetrics | null {
    const live = this.livePriceFor(assetTypeId);
    if (!live) {
      return null;
    }

    const fx = this.panel(categoryId).fxUsdToEur ?? 1;
    const quoteCurrency = this.displayCurrencyCode(live.currency);
    const showEurToggle = this.isUsdLikeCurrency(live.currency);
    const showEur = showEurToggle && this.isLivePriceEurMode(assetTypeId);

    const nativePrice = live.price;
    const displayPrice = showEur ? this.amountToEur(nativePrice, live.currency, fx) : nativePrice;
    const displayCurrency = showEur ? 'EUR' : quoteCurrency;

    const unitCount = units ?? null;
    if (unitCount === null || unitCount <= 0) {
      return {
        price: displayPrice,
        currency: displayCurrency,
        showEurToggle,
        marketValue: null,
        profit: null,
        profitPct: null,
      };
    }

    const marketValue = this.round2(unitCount * displayPrice);

    let profit: number;
    let profitBasis: number;

    if (showEur) {
      const marketEur = this.round2(unitCount * this.amountToEur(nativePrice, live.currency, fx));
      profit = this.round2(marketEur - costEur);
      profitBasis = costEur;
    } else if (quoteCurrency === assetCurrency) {
      profit = this.round2(marketValue - costNative);
      profitBasis = costNative;
    } else if (this.isUsdLikeCurrency(live.currency)) {
      const costInQuote = assetCurrency === 'EUR' ? costEur / fx : costNative;
      profit = this.round2(marketValue - costInQuote);
      profitBasis = costInQuote;
    } else {
      const marketEur = this.round2(unitCount * this.amountToEur(nativePrice, live.currency, fx));
      profit = this.round2(marketEur - costEur);
      profitBasis = costEur;
    }

    const profitPct = profitBasis > 0 ? this.round2((profit / profitBasis) * 100) : 0;

    return {
      price: displayPrice,
      currency: displayCurrency,
      showEurToggle,
      marketValue,
      profit,
      profitPct,
    };
  }

  private amountToEur(amount: number, currency: string, fxRate: number): number {
    if (currency === 'EUR') {
      return amount;
    }
    if (currency === 'USD' || currency === 'USDT') {
      return this.round2(amount * fxRate);
    }
    return amount;
  }

  private round2(value: number): number {
    return Math.round(value * 100) / 100;
  }

  private loadOverview(): void {
    this.loading.set(true);
    this.errorMessage.set(null);
    this.api.getOverview(this.year(), this.month()).subscribe({
      next: (response) => {
        this.overview.set(response);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
        this.overview.set(null);
        this.errorMessage.set('No se pudo cargar el detalle de inversión.');
      },
    });
  }

  panel(categoryId: string): CategoryPanelState {
    return this.panels()[categoryId] ?? createPanelState();
  }

  private updatePanel(categoryId: string, patch: Partial<CategoryPanelState>): void {
    this.panels.update((current) => ({
      ...current,
      [categoryId]: { ...(current[categoryId] ?? createPanelState()), ...patch },
    }));
  }

  isPanelOpen(categoryId: string): boolean {
    return this.panel(categoryId).open;
  }

  togglePanel(categoryId: string): void {
    const p = this.panel(categoryId);
    const willOpen = !p.open;
    this.updatePanel(categoryId, { open: willOpen });
    if (willOpen && !p.detail) {
      this.loadCategoryDetail(categoryId);
    }
  }

  openPanel(categoryId: string): void {
    if (!this.panel(categoryId).open) {
      this.togglePanel(categoryId);
    }
  }

  private loadCategoryDetail(categoryId: string): void {
    this.updatePanel(categoryId, { loadingDetail: true, errorMessage: null });
    this.api.getCategoryDetail(this.year(), this.month(), categoryId).subscribe({
      next: (detail) => this.applyDetail(categoryId, detail),
      error: () => {
        this.updatePanel(categoryId, {
          loadingDetail: false,
          errorMessage: 'No se pudo cargar el detalle de la categoría.',
        });
      },
    });
  }

  private applyDetail(categoryId: string, detail: CategoryDetailResponse): void {
    const assetRows = this.buildAssetRows(detail);
    const categoryTotalInput = this.initialCategoryTotalInput(detail);
    const autoEdit = detail.allocated_amount_eur <= 0;

    this.updatePanel(categoryId, {
      loadingDetail: false,
      detail,
      assetEditMode: autoEdit,
      assetRows,
      fxUsdToEur: detail.fx_usd_to_eur,
      categoryTotalInput,
      editSnapshot: null,
    });

    if (autoEdit) {
      this.clampCategoryTotalToAllocated(categoryId);
      this.refreshEditSnapshot(categoryId);
    }
  }

  private refreshEditSnapshot(categoryId: string): void {
    const detail = this.panel(categoryId).detail;
    if (!detail) {
      return;
    }
    this.updatePanel(categoryId, {
      editSnapshot: this.snapshotFromSavedDetail(detail),
    });
  }

  private initialCategoryTotalInput(detail: CategoryDetailResponse): string {
    return toInputString(Math.max(detail.category_amount_eur, detail.allocated_amount_eur));
  }

  /** Baseline en BD (sin previsión de transacciones) para detectar cambios pendientes. */
  private snapshotFromSavedDetail(detail: CategoryDetailResponse): AssetEditSnapshot {
    return {
      assetRows: detail.assets.map((asset) => ({
        assetTypeId: asset.asset_type_id,
        amount: toInputString(asset.amount),
        units: toInputString(asset.units),
      })),
      categoryTotalInput: this.initialCategoryTotalInput(detail),
    };
  }

  hasPendingAssetChanges(categoryId: string): boolean {
    const p = this.panel(categoryId);
    if (!p.assetEditMode || !p.editSnapshot) {
      return false;
    }

    if (p.categoryTotalInput.trim() !== p.editSnapshot.categoryTotalInput.trim()) {
      return true;
    }

    if (p.assetRows.length !== p.editSnapshot.assetRows.length) {
      return true;
    }

    const snapshotById = new Map(p.editSnapshot.assetRows.map((row) => [row.assetTypeId, row]));
    for (const row of p.assetRows) {
      const previous = snapshotById.get(row.assetTypeId);
      if (!previous) {
        return true;
      }
      if (row.amount.trim() !== previous.amount.trim() || row.units.trim() !== previous.units.trim()) {
        return true;
      }
    }

    return false;
  }

  canSaveAssets(categoryId: string): boolean {
    const p = this.panel(categoryId);
    return !p.savingAssets && this.hasPendingAssetChanges(categoryId);
  }

  /**
   * Previsión del total manual: entidades vinculadas > mes anterior + aportaciones mensuales de activos.
   */
  suggestedAmount(cat: CategoryOverview): number {
    if (cat.entity_amount_eur > 0) {
      return cat.entity_amount_eur;
    }
    if (cat.suggested_amount_eur !== null && cat.suggested_amount_eur !== undefined) {
      return cat.suggested_amount_eur;
    }
    return cat.previous_amount_eur ?? 0;
  }

  onAssetAmountChange(categoryId: string, assetTypeId: string, value: string): void {
    const rows = this.panel(categoryId).assetRows.map((r) =>
      r.assetTypeId === assetTypeId ? { ...r, amount: value } : r,
    );
    this.updatePanel(categoryId, { assetRows: rows });
    this.clampCategoryTotalToAllocated(categoryId);
  }

  formatMonthlyContribution(value: number | null, currency: string): string | null {
    if (value === null || value <= 0) {
      return null;
    }
    const formatted = String(value).replace('.', ',');
    return `+${formatted} ${currency}/mes`;
  }

  categoryInputPercentage(categoryId: string): string {
    const total = this.overview()?.total_invested ?? 0;
    if (!total) return '0.0';
    const value = this.categoryTotalDisplay(categoryId);
    return ((value / total) * 100).toFixed(1);
  }

  /** Total de categoría declarado (sidebar / donut). En edición puede superar la suma de activos. */
  categoryTotalDisplay(categoryId: string): number {
    const p = this.panel(categoryId);
    if (p.assetEditMode) {
      const allocated = this.assetAllocatedFor(categoryId);
      const parsed = parseDecimalInput(p.categoryTotalInput);
      const value = parsed === null ? allocated : parsed;
      return Math.max(value, allocated);
    }
    return p.detail?.category_amount_eur ?? 0;
  }

  categoryTotalInputDisplay(categoryId: string): string {
    const p = this.panel(categoryId);
    if (p.assetEditMode) {
      return p.categoryTotalInput;
    }
    return String(this.categoryTotalDisplay(categoryId)).replace('.', ',');
  }

  categoryOthersDisplay(categoryId: string): number {
    const p = this.panel(categoryId);
    if (p.assetEditMode) {
      return Math.max(0, this.categoryTotalDisplay(categoryId) - this.assetAllocatedFor(categoryId));
    }
    return p.detail?.others_amount_eur ?? 0;
  }

  onCategoryTotalChange(categoryId: string, value: string): void {
    this.updatePanel(categoryId, { categoryTotalInput: value });
  }

  onCategoryTotalBlur(categoryId: string): void {
    this.clampCategoryTotalToAllocated(categoryId);
  }

  private clampCategoryTotalToAllocated(categoryId: string): void {
    const p = this.panel(categoryId);
    if (!p.assetEditMode) {
      return;
    }
    const allocated = Math.round(this.assetAllocatedFor(categoryId) * 100) / 100;
    const parsed = parseDecimalInput(p.categoryTotalInput);
    if (parsed === null || parsed < allocated) {
      this.updatePanel(categoryId, { categoryTotalInput: toInputString(allocated) });
    }
  }

  private buildAssetRows(detail: CategoryDetailResponse): AssetRow[] {
    return detail.assets.map((asset) => {
      const hasSaved = asset.amount > 0 || asset.units !== null;
      const fallbackAmount = asset.suggested_amount ?? asset.previous_amount ?? 0;
      return {
        assetTypeId: asset.asset_type_id,
        name: asset.name,
        ticker: asset.ticker,
        currency: asset.currency,
        amount: toInputString(hasSaved ? asset.amount : fallbackAmount),
        units: toInputString(hasSaved ? asset.units : (asset.suggested_units ?? asset.previous_units ?? null)),
        monthlyContribution: asset.monthly_contribution,
        hasTransactions: asset.has_transactions ?? false,
      };
    });
  }

  private transactionReloadKey(categoryId: string, assetTypeId: string): string {
    return `${categoryId}:${assetTypeId}`;
  }

  isLoadingTransactionReload(categoryId: string, assetTypeId: string): boolean {
    return this.transactionReloadLoading()[this.transactionReloadKey(categoryId, assetTypeId)] ?? false;
  }

  applyTransactionTotals(categoryId: string, assetTypeId: string): void {
    const key = this.transactionReloadKey(categoryId, assetTypeId);
    this.transactionReloadLoading.update((current) => ({ ...current, [key]: true }));

    this.api.getAssetTransactionPreview(this.year(), this.month(), assetTypeId).subscribe({
      next: (preview) => {
        const rows = this.panel(categoryId).assetRows.map((row) =>
          row.assetTypeId === assetTypeId
            ? {
                ...row,
                amount: toInputString(preview.amount),
                units: toInputString(preview.units),
              }
            : row,
        );
        this.updatePanel(categoryId, { assetRows: rows });
        this.clampCategoryTotalToAllocated(categoryId);
        this.transactionReloadLoading.update((current) => ({ ...current, [key]: false }));
      },
      error: () => {
        this.transactionReloadLoading.update((current) => ({ ...current, [key]: false }));
        this.updatePanel(categoryId, {
          errorMessage: 'No se pudieron calcular los totales desde las transacciones del activo.',
        });
      },
    });
  }

  assetSegmentsFor(categoryId: string): DonutSegment[] {
    const detail = this.panel(categoryId).detail;
    if (!detail) return [];
    const segments: DonutSegment[] = detail.assets
      .filter((a) => a.amount_eur > 0)
      .map((a, i) => ({
        id: a.asset_type_id,
        label: a.name,
        value: a.amount_eur,
        color: this.fallbackColor(i),
      }));
    if (detail.others_amount_eur > 0) {
      segments.push({ id: '__others__', label: 'Otros', value: detail.others_amount_eur, color: this.othersColor() });
    }
    return segments;
  }

  assetAllocatedFor(categoryId: string): number {
    return this.panel(categoryId).assetRows.reduce(
      (sum, row) => sum + this.assetRowPreviewEur(categoryId, row),
      0,
    );
  }

  /** Equivalente en EUR usando el tipo de cambio del backend para el mes activo. */
  assetRowPreviewEur(categoryId: string, row: AssetRow): number {
    const value = parseDecimalInput(row.amount) ?? 0;
    if (row.currency === 'EUR') return value;
    const rate = this.panel(categoryId).fxUsdToEur ?? 1;
    return Math.round(value * rate * 100) / 100;
  }

  assetGridCols(currency: string): string {
    if (currency === 'USD') return 'sm:grid-cols-3';
    return 'sm:grid-cols-2';
  }

  onAssetUnitsChange(categoryId: string, assetTypeId: string, value: string): void {
    const rows = this.panel(categoryId).assetRows.map((r) =>
      r.assetTypeId === assetTypeId ? { ...r, units: value } : r,
    );
    this.updatePanel(categoryId, { assetRows: rows });
  }

  openAssetEditDialog(categoryId: string, asset: AssetInvestmentDetail): void {
    this.assetEditCategoryId.set(categoryId);
    this.assetEditTarget.set(asset);
    this.assetEditDialogOpen.set(true);
  }

  closeAssetEditDialog(): void {
    this.assetEditDialogOpen.set(false);
    this.assetEditCategoryId.set(null);
    this.assetEditTarget.set(null);
  }

  onAssetEditSaved(categoryId: string): void {
    this.refreshMarketPrices(true);
    this.api.getCategoryDetail(this.year(), this.month(), categoryId).subscribe({
      next: (detail) => {
        this.applyDetail(categoryId, detail);
        this.closeAssetEditDialog();
      },
      error: () => {
        this.updatePanel(categoryId, {
          errorMessage: 'Se guardó el activo, pero no se pudo refrescar el detalle.',
        });
        this.closeAssetEditDialog();
      },
    });
  }

  toggleAssetEditMode(categoryId: string): void {
    const p = this.panel(categoryId);
    const enteringEdit = !p.assetEditMode;

    if (enteringEdit && p.detail) {
      const assetRows = this.buildAssetRows(p.detail);
      const categoryTotalInput = this.initialCategoryTotalInput(p.detail);
      this.updatePanel(categoryId, {
        assetEditMode: true,
        assetRows,
        categoryTotalInput,
        editSnapshot: null,
        showAddAsset: false,
        errorMessage: null,
      });
      this.clampCategoryTotalToAllocated(categoryId);
      this.refreshEditSnapshot(categoryId);
      return;
    }

    this.updatePanel(categoryId, {
      assetEditMode: false,
      editSnapshot: null,
      showAddAsset: false,
      errorMessage: null,
      assetRows: p.detail ? this.buildAssetRows(p.detail) : p.assetRows,
      categoryTotalInput: p.detail ? this.initialCategoryTotalInput(p.detail) : p.categoryTotalInput,
    });
  }

  saveAssets(categoryId: string): void {
    const p = this.panel(categoryId);
    if (!p.detail) return;

    if (!this.hasPendingAssetChanges(categoryId)) {
      return;
    }

    this.clampCategoryTotalToAllocated(categoryId);
    const allocated = this.assetAllocatedFor(categoryId);
    const total = this.categoryTotalDisplay(categoryId);
    if (total + 0.001 < allocated) {
      this.updatePanel(categoryId, {
        errorMessage: `El total de categoría no puede ser inferior a la suma de activos (${allocated.toFixed(2)} €).`,
      });
      return;
    }

    this.updatePanel(categoryId, { savingAssets: true, errorMessage: null });
    const payload = {
      assets: p.assetRows.map((row) => ({
        asset_type_id: row.assetTypeId,
        amount: parseDecimalInput(row.amount) ?? 0,
        units: parseDecimalInput(row.units),
      })),
      category_amount_eur: this.categoryTotalDisplay(categoryId),
    };
    this.api.upsertCategoryAssets(this.year(), this.month(), categoryId, payload).subscribe({
      next: (response) => {
        const assetRows = this.buildAssetRows(response);
        const categoryTotalInput = this.initialCategoryTotalInput(response);
        this.updatePanel(categoryId, {
          detail: response,
          savingAssets: false,
          assetEditMode: false,
          assetRows,
          categoryTotalInput,
          editSnapshot: null,
          fxUsdToEur: response.fx_usd_to_eur,
        });
        this.loadOverview();
      },
      error: (err) => {
        this.updatePanel(categoryId, {
          savingAssets: false,
          errorMessage: this.extractError(err, 'No se pudo guardar el reparto de activos.'),
        });
      },
    });
  }

  toggleAddAsset(categoryId: string): void {
    const p = this.panel(categoryId);
    this.updatePanel(categoryId, {
      showAddAsset: !p.showAddAsset,
      newAssetName: '',
      newAssetTicker: '',
      newAssetCurrency: 'EUR',
    });
  }

  onNewAssetNameChange(categoryId: string, value: string): void {
    this.updatePanel(categoryId, { newAssetName: value });
  }

  onNewAssetTickerChange(categoryId: string, value: string): void {
    this.updatePanel(categoryId, { newAssetTicker: value });
  }

  onNewAssetCurrencyChange(categoryId: string, value: string): void {
    this.updatePanel(categoryId, { newAssetCurrency: value });
  }

  createAsset(categoryId: string): void {
    const p = this.panel(categoryId);
    const name = p.newAssetName.trim();
    if (!name) return;

    this.updatePanel(categoryId, { creatingAsset: true, errorMessage: null });
    this.api
      .createAssetType({
        category_id: categoryId,
        name,
        ticker: p.newAssetTicker.trim() || null,
        currency: p.newAssetCurrency,
      })
      .subscribe({
        next: (asset: AssetType) => {
          const rows = [
            ...this.panel(categoryId).assetRows,
            {
              assetTypeId: asset.id,
              name: asset.name,
              ticker: asset.ticker,
              currency: asset.currency,
              amount: '0',
              units: '',
              monthlyContribution: asset.monthly_contribution,
              hasTransactions: false,
            },
          ];
          this.updatePanel(categoryId, { creatingAsset: false, showAddAsset: false, assetRows: rows });
        },
        error: (err) => {
          this.updatePanel(categoryId, {
            creatingAsset: false,
            errorMessage: this.extractError(err, 'No se pudo crear el activo.'),
          });
        },
      });
  }

  private fallbackPalette(): string[] {
    const el = this.host.nativeElement;
    return FALLBACK_DEFAULTS.map((fallback, index) =>
      readCssVar(el, `--fallback-color-${index + 1}`, fallback),
    );
  }

  private fallbackColor(index: number): string {
    const palette = this.fallbackPalette();
    return palette[index % palette.length];
  }

  private othersColor(): string {
    return readCssVar(this.host.nativeElement, '--others-color', '#64748b');
  }

  private extractError(err: unknown, fallback: string): string {
    const httpError = err as { error?: { detail?: string } };
    return httpError?.error?.detail ?? fallback;
  }
}
