import { Component, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { InvestmentApiService } from '../../core/services/investment-api.service';
import { PeriodStorageService } from '../../core/services/period-storage.service';
import {
  AssetType,
  CategoryDetailResponse,
  CategoryOverview,
  InvestmentOverviewResponse,
} from '../../core/models/investment.model';
import { MONTH_NAMES } from '../../core/models/month-names';
import { EurCurrencyPipe } from '../../core/pipes/eur-currency.pipe';
import { DonutSegment, SegmentDonutChartComponent } from '../../shared/components/segment-donut-chart/segment-donut-chart.component';
import { parseDecimalInput } from '../../core/utils/parse-decimal';

const FALLBACK_PALETTE = ['#f59e0b', '#6366f1', '#22c55e', '#ec4899', '#06b6d4', '#eab308', '#f43f5e'];
const OTHERS_COLOR = '#64748b';

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
}

interface CategoryPanelState {
  open: boolean;
  loadingDetail: boolean;
  detail: CategoryDetailResponse | null;
  errorMessage: string | null;
  categoryInput: string;
  savingTotal: boolean;
  assetEditMode: boolean;
  assetRows: AssetRow[];
  fxUsdToEur: number | null;
  savingAssets: boolean;
  showAddAsset: boolean;
  newAssetName: string;
  newAssetTicker: string;
  newAssetCurrency: string;
  creatingAsset: boolean;
}

function createPanelState(): CategoryPanelState {
  return {
    open: false,
    loadingDetail: false,
    detail: null,
    errorMessage: null,
    categoryInput: '',
    savingTotal: false,
    assetEditMode: false,
    assetRows: [],
    fxUsdToEur: null,
    savingAssets: false,
    showAddAsset: false,
    newAssetName: '',
    newAssetTicker: '',
    newAssetCurrency: 'EUR',
    creatingAsset: false,
  };
}

@Component({
  selector: 'app-investment-detail',
  imports: [RouterLink, DecimalPipe, EurCurrencyPipe, SegmentDonutChartComponent],
  templateUrl: './investment-detail.component.html',
})
export class InvestmentDetailComponent {
  private readonly api = inject(InvestmentApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly periodStorage = inject(PeriodStorageService);

  readonly monthNames = MONTH_NAMES;

  private readonly storedPeriod = this.periodStorage.read();
  readonly year = signal<number>(this.storedPeriod.year);
  readonly month = signal<number>(this.storedPeriod.month);

  readonly loading = signal<boolean>(false);
  readonly errorMessage = signal<string | null>(null);

  readonly overview = signal<InvestmentOverviewResponse | null>(null);
  readonly panels = signal<Record<string, CategoryPanelState>>({});

  readonly monthLabel = computed(() => `${this.monthNames[this.month() - 1]} ${this.year()}`);

  readonly categorySegments = computed<DonutSegment[]>(() => {
    const ov = this.overview();
    if (!ov) return [];
    return ov.categories.map((c, i) => ({
      id: c.category_id,
      label: c.name,
      value: c.amount_eur,
      color: c.color ?? FALLBACK_PALETTE[i % FALLBACK_PALETTE.length],
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
    const catOverview = this.overview()?.categories.find((c) => c.category_id === categoryId) ?? null;
    const categoryInput = toInputString(
      catOverview ? (catOverview.saved_this_month ? catOverview.amount_eur : this.suggestedAmount(catOverview)) : null,
    );

    this.updatePanel(categoryId, {
      loadingDetail: false,
      detail,
      assetEditMode: detail.allocated_amount_eur <= 0,
      assetRows: this.buildAssetRows(detail),
      fxUsdToEur: detail.fx_usd_to_eur,
      categoryInput,
    });
  }

  /**
   * Valor sugerido para precargar el total manual: prioriza el importe ya conocido de las
   * entidades vinculadas a esta categoría (p.ej. KuCoin → Crypto) sobre el mes anterior,
   * ya que refleja el saldo real de este mes en vez de un dato desactualizado.
   */
  suggestedAmount(cat: CategoryOverview): number {
    return cat.entity_amount_eur > 0 ? cat.entity_amount_eur : (cat.previous_amount_eur ?? 0);
  }

  onCategoryInputChange(categoryId: string, value: string): void {
    this.updatePanel(categoryId, { categoryInput: value });
  }

  /** Valor numérico del input de categoría, para usarlo en el slider y en cálculos. */
  categoryInputNumeric(categoryId: string): number {
    return parseDecimalInput(this.panel(categoryId).categoryInput) ?? 0;
  }

  categoryInputPercentage(categoryId: string): string {
    const total = this.overview()?.total_invested ?? 0;
    if (!total) return '0.0';
    const value = this.categoryInputNumeric(categoryId);
    return ((value / total) * 100).toFixed(1);
  }

  saveCategoryTotal(categoryId: string): void {
    const p = this.panel(categoryId);
    this.updatePanel(categoryId, { savingTotal: true, errorMessage: null });
    const amount = parseDecimalInput(p.categoryInput) ?? 0;
    const payload = { categories: [{ category_id: categoryId, amount_eur: amount }] };
    this.api.upsertCategories(this.year(), this.month(), payload).subscribe({
      next: (response) => {
        this.overview.set(response);
        const updatedCat = response.categories.find((c) => c.category_id === categoryId);
        this.updatePanel(categoryId, {
          savingTotal: false,
          categoryInput: updatedCat ? toInputString(updatedCat.amount_eur) : p.categoryInput,
        });
      },
      error: (err) => {
        this.updatePanel(categoryId, {
          savingTotal: false,
          errorMessage: this.extractError(err, 'No se pudo guardar el total.'),
        });
      },
    });
  }

  private buildAssetRows(detail: CategoryDetailResponse): AssetRow[] {
    return detail.assets.map((asset) => {
      const hasSaved = asset.amount > 0 || asset.units !== null;
      return {
        assetTypeId: asset.asset_type_id,
        name: asset.name,
        ticker: asset.ticker,
        currency: asset.currency,
        amount: toInputString(hasSaved ? asset.amount : (asset.previous_amount ?? 0)),
        units: toInputString(hasSaved ? asset.units : (asset.previous_units ?? null)),
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
        label: a.ticker ?? a.name,
        value: a.amount_eur,
        color: FALLBACK_PALETTE[i % FALLBACK_PALETTE.length],
      }));
    if (detail.others_amount_eur > 0) {
      segments.push({ id: '__others__', label: 'Otros', value: detail.others_amount_eur, color: OTHERS_COLOR });
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

  assetOthersFor(categoryId: string): number {
    const detail = this.panel(categoryId).detail;
    if (!detail) return 0;
    return Math.round((detail.category_amount_eur - this.assetAllocatedFor(categoryId)) * 100) / 100;
  }

  showUnitsFor(categoryId: string): boolean {
    return this.panel(categoryId).detail?.has_units ?? false;
  }

  assetGridCols(categoryId: string, currency: string): string {
    const hasUnits = this.showUnitsFor(categoryId);
    if (hasUnits && currency === 'USD') return 'sm:grid-cols-3';
    if (hasUnits || currency === 'USD') return 'sm:grid-cols-2';
    return '';
  }

  onAssetAmountChange(categoryId: string, assetTypeId: string, value: string): void {
    const rows = this.panel(categoryId).assetRows.map((r) =>
      r.assetTypeId === assetTypeId ? { ...r, amount: value } : r,
    );
    this.updatePanel(categoryId, { assetRows: rows });
  }

  onAssetUnitsChange(categoryId: string, assetTypeId: string, value: string): void {
    const rows = this.panel(categoryId).assetRows.map((r) =>
      r.assetTypeId === assetTypeId ? { ...r, units: value } : r,
    );
    this.updatePanel(categoryId, { assetRows: rows });
  }

  toggleAssetEditMode(categoryId: string): void {
    const p = this.panel(categoryId);
    this.updatePanel(categoryId, {
      assetEditMode: !p.assetEditMode,
      assetRows: p.detail ? this.buildAssetRows(p.detail) : p.assetRows,
      errorMessage: null,
    });
  }

  saveAssets(categoryId: string): void {
    const p = this.panel(categoryId);
    if (!p.detail) return;

    this.updatePanel(categoryId, { savingAssets: true, errorMessage: null });
    const payload = {
      assets: p.assetRows.map((row) => ({
        asset_type_id: row.assetTypeId,
        amount: parseDecimalInput(row.amount) ?? 0,
        units: parseDecimalInput(row.units),
      })),
    };
    this.api.upsertCategoryAssets(this.year(), this.month(), categoryId, payload).subscribe({
      next: (response) => {
        this.updatePanel(categoryId, {
          detail: response,
          savingAssets: false,
          assetEditMode: false,
          assetRows: this.buildAssetRows(response),
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

  private extractError(err: unknown, fallback: string): string {
    const httpError = err as { error?: { detail?: string } };
    return httpError?.error?.detail ?? fallback;
  }
}
