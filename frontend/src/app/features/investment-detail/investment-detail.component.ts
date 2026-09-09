import { Component, computed, ElementRef, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ActivatedRoute } from '@angular/router';

import { InvestmentApiService } from '../../core/services/investment-api.service';
import { PeriodStorageService } from '../../core/services/period-storage.service';
import {
  AssetInvestmentDetail,
  AssetType,
  CategoryDetailResponse,
  CategoryOverview,
  InvestmentOverviewResponse,
} from '../../core/models/investment.model';
import { AssetEditDialogComponent } from './components/asset-edit-dialog/asset-edit-dialog.component';
import { MONTH_NAMES } from '../../core/models/month-names';
import { EurCurrencyPipe } from '../../core/pipes/eur-currency.pipe';
import { DonutSegment, SegmentDonutChartComponent } from '../../shared/components/segment-donut-chart/segment-donut-chart.component';
import { parseDecimalInput } from '../../core/utils/parse-decimal';
import { readCssVar } from '../../core/utils/read-css-var';

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
  imports: [DecimalPipe, EurCurrencyPipe, SegmentDonutChartComponent, AssetEditDialogComponent],
  templateUrl: './investment-detail.component.html',
  styleUrl: './investment-detail.component.scss',
})
export class InvestmentDetailComponent {
  private readonly api = inject(InvestmentApiService);
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
    const current = this.panel(categoryId);
    this.updatePanel(categoryId, {
      editSnapshot: this.snapshotFrom(current.assetRows, current.categoryTotalInput),
    });
  }

  private initialCategoryTotalInput(detail: CategoryDetailResponse): string {
    return toInputString(Math.max(detail.category_amount_eur, detail.allocated_amount_eur));
  }

  private snapshotFrom(assetRows: AssetRow[], categoryTotalInput: string): AssetEditSnapshot {
    return {
      assetRows: assetRows.map((row) => ({
        assetTypeId: row.assetTypeId,
        amount: row.amount,
        units: row.units,
      })),
      categoryTotalInput,
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
    const allocated = this.assetAllocatedFor(categoryId);
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
