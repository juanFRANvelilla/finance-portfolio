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
  CategoryDetailResponse,
  CategoryOverview,
  InvestmentOverviewResponse,
} from '../../core/models/investment.model';
import { MarketPriceResponse } from '../../core/models/market-price.model';
import { AssetEditDialogComponent } from './components/asset-edit-dialog/asset-edit-dialog.component';
import { AssetMonthlyPositionDialogComponent } from './components/asset-monthly-position-dialog/asset-monthly-position-dialog.component';
import { AssetSaleDialogComponent } from './components/asset-sale-dialog/asset-sale-dialog.component';
import { MONTH_NAMES } from '../../core/models/month-names';
import { EurCurrencyPipe } from '../../core/pipes/eur-currency.pipe';
import { DonutSegment, SegmentDonutChartComponent } from '../../shared/components/segment-donut-chart/segment-donut-chart.component';
import { parseDecimalInput } from '../../core/utils/parse-decimal';
import { readCssVar } from '../../core/utils/read-css-var';
import {
  amountToEur,
  assetMarketValueEur as computeAssetMarketValueEur,
  computeCategoryLiveSummary,
  computePortfolioLiveSummaryFromDetails,
  LiveInvestmentSummary,
  LivePriceByAssetId,
  marketPricesToMap,
  round2,
} from '../../core/utils/live-investment-summary';

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

interface CategoryPanelState {
  open: boolean;
  loadingDetail: boolean;
  detail: CategoryDetailResponse | null;
  errorMessage: string | null;
  assetEditMode: boolean;
  assetRows: AssetRow[];
  fxUsdToEur: number | null;
  showAddAsset: boolean;
  newAssetName: string;
  newAssetTicker: string;
  newAssetCurrency: string;
  creatingAsset: boolean;
  /** Borrador mientras se edita el total de categoría inline. */
  categoryTotalDraft: string;
  categoryTotalEditing: boolean;
  savingCategoryTotal: boolean;
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
    showAddAsset: false,
    newAssetName: '',
    newAssetTicker: '',
    newAssetCurrency: 'EUR',
    creatingAsset: false,
    categoryTotalDraft: '',
    categoryTotalEditing: false,
    savingCategoryTotal: false,
  };
}

@Component({
  selector: 'app-investment-detail',
  imports: [
    CurrencyPipe,
    DecimalPipe,
    EurCurrencyPipe,
    SegmentDonutChartComponent,
    AssetEditDialogComponent,
    AssetMonthlyPositionDialogComponent,
    AssetSaleDialogComponent,
  ],
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

  readonly assetMonthlyDialogOpen = signal(false);
  readonly assetMonthlyCategoryId = signal<string | null>(null);
  readonly assetMonthlyTarget = signal<AssetInvestmentDetail | null>(null);
  readonly assetMonthlyDraftAmount = signal('');
  readonly assetMonthlyDraftUnits = signal('');

  readonly assetSaleDialogOpen = signal(false);
  readonly assetSaleCategoryId = signal<string | null>(null);
  readonly assetSaleTarget = signal<AssetInvestmentDetail | null>(null);
  /** Precios de mercado en vivo (GET /api/v1/market-prices), indexados por asset_type_id. */
  readonly marketPrices = signal<Record<string, MarketPriceResponse>>({});

  /** Por activo: si true, precio/valor/P/L se muestran convertidos a EUR (USD/USDT). */
  readonly livePriceEurMode = signal<Record<string, boolean>>({});

  /** Panel de info de P/L agregado abierto por categoría. */
  readonly categoryProfitInfoOpen = signal<Record<string, boolean>>({});

  /** Panel de valor de mercado total (sección «Total invertido»). */
  readonly totalProfitInfoOpen = signal(false);

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

  toggleTotalProfitInfo(): void {
    const willOpen = !this.totalProfitInfoOpen();
    this.totalProfitInfoOpen.set(willOpen);
    if (willOpen) {
      this.ensureAllCategoryDetailsLoaded();
    }
  }

  isPortfolioSummaryLoading(): boolean {
    if (!this.totalProfitInfoOpen()) {
      return false;
    }
    const overview = this.overview();
    if (!overview) {
      return false;
    }
    return overview.categories.some((cat) => {
      const state = this.panel(cat.category_id);
      return !state.detail && state.loadingDetail;
    });
  }

  /** Valor de mercado total en EUR y balance vs total invertido registrado. */
  portfolioLiveSummary(): LiveInvestmentSummary {
    const overview = this.overview();
    if (!overview) {
      return { marketValueEur: 0, profitEur: 0, profitPct: 0, assetCount: 0, hasData: false };
    }

    const details: CategoryDetailResponse[] = [];
    for (const cat of overview.categories) {
      const detail = this.panel(cat.category_id).detail;
      if (!detail) {
        return { marketValueEur: 0, profitEur: 0, profitPct: 0, assetCount: 0, hasData: false };
      }
      details.push(detail);
    }

    return computePortfolioLiveSummaryFromDetails(
      overview.categories.map((cat) => ({
        categoryId: cat.category_id,
        investedEur: cat.amount_eur,
      })),
      details,
      this.livePricesMap(),
      overview.total_invested,
    );
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

  /** Valor de mercado de la categoría y balance vs total invertido de la categoría. */
  categoryLiveSummary(categoryId: string): LiveInvestmentSummary {
    const overview = this.overview();
    const detail = this.panel(categoryId).detail;
    const category = overview?.categories.find((cat) => cat.category_id === categoryId);
    if (!detail || !category) {
      return { marketValueEur: 0, profitEur: 0, profitPct: 0, assetCount: 0, hasData: false };
    }

    return this.buildCategoryLiveSummary(
      categoryId,
      category.amount_eur,
      detail,
      this.livePricesMap(),
    );
  }

  private buildCategoryLiveSummary(
    categoryId: string,
    investedEur: number,
    detail: CategoryDetailResponse,
    prices: LivePriceByAssetId,
  ): LiveInvestmentSummary {
    return computeCategoryLiveSummary(
      {
        investedEur,
        othersAmountEur: detail.others_amount_eur,
        assets: detail.assets,
        fxUsdToEur: this.panel(categoryId).fxUsdToEur ?? 1,
      },
      prices,
    );
  }

  private livePricesMap(): LivePriceByAssetId {
    return marketPricesToMap(Object.values(this.marketPrices()));
  }

  /** Valor de mercado de un activo en EUR (precio en vivo × títulos). */
  private assetMarketValueEur(asset: AssetInvestmentDetail, categoryId: string): number | null {
    const fx = this.panel(categoryId).fxUsdToEur ?? 1;
    return computeAssetMarketValueEur(asset, fx, this.livePricesMap());
  }

  /** P/L de un activo siempre normalizado a EUR (para agregados de categoría). */
  private assetProfitEur(asset: AssetInvestmentDetail, categoryId: string): number | null {
    const marketEur = this.assetMarketValueEur(asset, categoryId);
    if (marketEur === null) {
      return null;
    }
    return round2(marketEur - asset.amount_eur);
  }

  private ensureAllCategoryDetailsLoaded(): void {
    const overview = this.overview();
    if (!overview) {
      return;
    }
    for (const cat of overview.categories) {
      const state = this.panel(cat.category_id);
      if (!state.detail && !state.loadingDetail) {
        this.loadCategoryDetail(cat.category_id);
      }
    }
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
    const displayPrice = showEur ? amountToEur(nativePrice, live.currency, fx) : nativePrice;
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

    const marketValue = round2(unitCount * displayPrice);

    let profit: number;
    let profitBasis: number;

    if (showEur) {
      const marketEur = round2(unitCount * amountToEur(nativePrice, live.currency, fx));
      profit = round2(marketEur - costEur);
      profitBasis = costEur;
    } else if (quoteCurrency === assetCurrency) {
      profit = round2(marketValue - costNative);
      profitBasis = costNative;
    } else if (this.isUsdLikeCurrency(live.currency)) {
      const costInQuote = assetCurrency === 'EUR' ? costEur / fx : costNative;
      profit = round2(marketValue - costInQuote);
      profitBasis = costInQuote;
    } else {
      const marketEur = round2(unitCount * amountToEur(nativePrice, live.currency, fx));
      profit = round2(marketEur - costEur);
      profitBasis = costEur;
    }

    const profitPct = profitBasis > 0 ? round2((profit / profitBasis) * 100) : 0;

    return {
      price: displayPrice,
      currency: displayCurrency,
      showEurToggle,
      marketValue,
      profit,
      profitPct,
    };
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
    const autoEdit = detail.allocated_amount_eur <= 0 && detail.assets.length === 0;

    this.updatePanel(categoryId, {
      loadingDetail: false,
      detail,
      assetEditMode: autoEdit,
      assetRows,
      fxUsdToEur: detail.fx_usd_to_eur,
      categoryTotalDraft: this.categoryTotalDisplayString(detail),
      categoryTotalEditing: false,
      savingCategoryTotal: false,
    });
  }

  private categoryTotalDisplayString(detail: CategoryDetailResponse): string {
    return String(Math.max(detail.category_amount_eur, detail.allocated_amount_eur)).replace('.', ',');
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

  /** Total de categoría declarado (sidebar / donut). */
  categoryTotalDisplay(categoryId: string): number {
    const p = this.panel(categoryId);
    if (p.categoryTotalEditing) {
      const allocated = p.detail?.allocated_amount_eur ?? 0;
      const parsed = parseDecimalInput(p.categoryTotalDraft);
      const value = parsed === null ? allocated : parsed;
      return Math.max(value, allocated);
    }
    return p.detail?.category_amount_eur ?? 0;
  }

  categoryTotalInputDisplay(categoryId: string): string {
    const p = this.panel(categoryId);
    if (p.categoryTotalEditing) {
      return p.categoryTotalDraft;
    }
    const detail = p.detail;
    return detail ? this.categoryTotalDisplayString(detail) : '';
  }

  categoryOthersDisplay(categoryId: string): number {
    const p = this.panel(categoryId);
    const allocated = p.detail?.allocated_amount_eur ?? 0;
    if (p.categoryTotalEditing) {
      return Math.max(0, this.categoryTotalDisplay(categoryId) - allocated);
    }
    return p.detail?.others_amount_eur ?? 0;
  }

  isCategoryTotalEditing(categoryId: string): boolean {
    return this.panel(categoryId).categoryTotalEditing;
  }

  startCategoryTotalEdit(categoryId: string): void {
    const detail = this.panel(categoryId).detail;
    if (!detail) {
      return;
    }
    this.updatePanel(categoryId, {
      categoryTotalEditing: true,
      categoryTotalDraft: this.categoryTotalDisplayString(detail),
      errorMessage: null,
    });
  }

  cancelCategoryTotalEdit(categoryId: string): void {
    const detail = this.panel(categoryId).detail;
    this.updatePanel(categoryId, {
      categoryTotalEditing: false,
      categoryTotalDraft: detail ? this.categoryTotalDisplayString(detail) : '',
    });
  }

  onCategoryTotalDraftChange(categoryId: string, value: string): void {
    this.updatePanel(categoryId, { categoryTotalDraft: value });
  }

  syncCategoryTotalToAllocated(categoryId: string): void {
    const allocated = this.panel(categoryId).detail?.allocated_amount_eur ?? 0;
    this.updatePanel(categoryId, {
      categoryTotalDraft: String(allocated).replace('.', ','),
    });
  }

  hasCategoryTotalPendingChange(categoryId: string): boolean {
    const p = this.panel(categoryId);
    if (!p.detail || !p.categoryTotalEditing) {
      return false;
    }
    const saved = Math.round(p.detail.category_amount_eur * 100) / 100;
    const draft = Math.round(this.categoryTotalDisplay(categoryId) * 100) / 100;
    return Math.abs(draft - saved) >= 0.005;
  }

  canConfirmCategoryTotal(categoryId: string): boolean {
    const p = this.panel(categoryId);
    if (!p.detail || p.savingCategoryTotal || !this.hasCategoryTotalPendingChange(categoryId)) {
      return false;
    }
    const allocated = p.detail.allocated_amount_eur;
    const total = this.categoryTotalDisplay(categoryId);
    return total + 0.001 >= allocated;
  }

  confirmCategoryTotal(categoryId: string): void {
    const p = this.panel(categoryId);
    if (!p.detail || !this.canConfirmCategoryTotal(categoryId)) {
      return;
    }

    this.updatePanel(categoryId, { savingCategoryTotal: true, errorMessage: null });
    this.api
      .upsertCategoryAssets(this.year(), this.month(), categoryId, {
        assets: [],
        category_amount_eur: this.categoryTotalDisplay(categoryId),
      })
      .subscribe({
        next: (response) => {
          this.applyDetail(categoryId, response);
          this.loadOverview();
        },
        error: (err) => {
          this.updatePanel(categoryId, {
            savingCategoryTotal: false,
            errorMessage: this.extractError(err, 'No se pudo guardar el total de categoría.'),
          });
        },
      });
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

  canSellAsset(asset: AssetInvestmentDetail): boolean {
    if ((asset.units ?? 0) > 0) {
      return true;
    }
    return asset.has_transactions;
  }

  openAssetEditDialog(categoryId: string, asset: AssetInvestmentDetail): void {
    this.assetEditCategoryId.set(categoryId);
    this.assetEditTarget.set(asset);
    this.assetEditDialogOpen.set(true);
  }

  openAssetMonthlyDialog(categoryId: string, asset: AssetInvestmentDetail): void {
    this.assetMonthlyCategoryId.set(categoryId);
    this.assetMonthlyTarget.set(asset);
    this.assetMonthlyDraftAmount.set(toInputString(asset.amount));
    this.assetMonthlyDraftUnits.set(toInputString(asset.units));
    this.assetMonthlyDialogOpen.set(true);
  }

  closeAssetMonthlyDialog(): void {
    this.assetMonthlyDialogOpen.set(false);
    this.assetMonthlyCategoryId.set(null);
    this.assetMonthlyTarget.set(null);
  }

  onAssetMonthlyDraftChange(draft: { amount: string; units: string }): void {
    this.assetMonthlyDraftAmount.set(draft.amount);
    this.assetMonthlyDraftUnits.set(draft.units);
  }

  liveMetricsForMonthlyDialog(): LivePriceMetrics | null {
    const asset = this.assetMonthlyTarget();
    const categoryId = this.assetMonthlyCategoryId();
    if (!asset || !categoryId) {
      return null;
    }
    const amountNative = parseDecimalInput(this.assetMonthlyDraftAmount()) ?? 0;
    const fx = this.panel(categoryId).fxUsdToEur ?? 1;
    const costEur =
      asset.currency === 'EUR' ? amountNative : Math.round(amountNative * fx * 100) / 100;
    return this.buildLiveMetrics(
      asset.asset_type_id,
      categoryId,
      parseDecimalInput(this.assetMonthlyDraftUnits()),
      costEur,
      amountNative,
      asset.currency,
    );
  }

  onAssetMonthlySaved(categoryId: string): void {
    this.closeAssetMonthlyDialog();
    this.api.getCategoryDetail(this.year(), this.month(), categoryId).subscribe({
      next: (detail) => {
        this.applyDetail(categoryId, detail);
        this.loadOverview();
      },
      error: () => {
        this.updatePanel(categoryId, {
          errorMessage: 'Se guardó la posición, pero no se pudo refrescar el detalle.',
        });
      },
    });
  }

  toggleMonthlyDialogEurMode(): void {
    const asset = this.assetMonthlyTarget();
    if (asset) {
      this.toggleLivePriceEur(asset.asset_type_id);
    }
  }

  openAssetSaleDialog(categoryId: string, asset: AssetInvestmentDetail): void {
    this.assetSaleCategoryId.set(categoryId);
    this.assetSaleTarget.set(asset);
    this.assetSaleDialogOpen.set(true);
  }

  closeAssetSaleDialog(): void {
    this.assetSaleDialogOpen.set(false);
    this.assetSaleCategoryId.set(null);
    this.assetSaleTarget.set(null);
  }

  onAssetSaleSaved(categoryId: string): void {
    this.closeAssetSaleDialog();
    this.api.getCategoryDetail(this.year(), this.month(), categoryId).subscribe({
      next: (detail) => this.applyDetail(categoryId, detail),
      error: () => {
        this.updatePanel(categoryId, {
          errorMessage: 'Venta registrada, pero no se pudo refrescar el detalle.',
        });
      },
    });
  }

  closeAssetEditDialog(): void {
    this.assetEditDialogOpen.set(false);
    this.assetEditCategoryId.set(null);
    this.assetEditTarget.set(null);
  }

  onAssetEditSaved(categoryId: string): void {
    const keepEditMode = this.panel(categoryId).assetEditMode;
    this.refreshMarketPrices(true);
    this.api.getCategoryDetail(this.year(), this.month(), categoryId).subscribe({
      next: (detail) => {
        this.applyDetail(categoryId, detail);
        if (keepEditMode) {
          this.updatePanel(categoryId, { assetEditMode: true });
        }
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
      this.updatePanel(categoryId, {
        assetEditMode: true,
        assetRows: this.buildAssetRows(p.detail),
        showAddAsset: false,
        errorMessage: null,
      });
      return;
    }

    this.updatePanel(categoryId, {
      assetEditMode: false,
      showAddAsset: false,
      errorMessage: null,
      assetRows: p.detail ? this.buildAssetRows(p.detail) : p.assetRows,
    });
  }

  assetDetailForRow(categoryId: string, assetTypeId: string): AssetInvestmentDetail | null {
    return this.panel(categoryId).detail?.assets.find((a) => a.asset_type_id === assetTypeId) ?? null;
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
        next: () => {
          const keepEditMode = this.panel(categoryId).assetEditMode;
          this.updatePanel(categoryId, { creatingAsset: false, showAddAsset: false });
          this.api.getCategoryDetail(this.year(), this.month(), categoryId).subscribe({
            next: (detail) => {
              this.applyDetail(categoryId, detail);
              if (keepEditMode) {
                this.updatePanel(categoryId, { assetEditMode: true });
              }
            },
            error: () => {
              this.updatePanel(categoryId, {
                errorMessage: 'Activo creado, pero no se pudo refrescar el detalle.',
              });
            },
          });
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
