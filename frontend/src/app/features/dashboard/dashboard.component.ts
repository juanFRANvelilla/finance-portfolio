import { DecimalPipe } from '@angular/common';
import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';
import { Observable, Subscription, catchError, forkJoin, of, switchMap, timer } from 'rxjs';

import { FinanceApiService } from '../../core/services/finance-api.service';
import { InvestmentApiService } from '../../core/services/investment-api.service';
import { MarketPriceApiService } from '../../core/services/market-price-api.service';
import { PeriodStorageService } from '../../core/services/period-storage.service';
import {
  AssetSalesListResponse,
  CategoryDetailResponse,
  InvestmentOverviewResponse,
} from '../../core/models/investment.model';
import { MarketPriceResponse } from '../../core/models/market-price.model';
import {
  computePortfolioLiveSummaryFromDetails,
  LiveInvestmentSummary,
  marketPricesToMap,
  round2,
} from '../../core/utils/live-investment-summary';
import { Entity } from '../../core/models/entity.model';
import {
  EntityBalanceInput,
  HybridBalanceImport,
  ImportPayload,
  MonthlyRecordResponse,
  TimelinePoint,
} from '../../core/models/monthly-record.model';
import { MONTH_NAMES } from '../../core/models/month-names';
import { EurCurrencyPipe } from '../../core/pipes/eur-currency.pipe';
import { DonutChartComponent } from './components/donut-chart/donut-chart.component';
import { AssetSalesListDialogComponent } from './components/asset-sales-list-dialog/asset-sales-list-dialog.component';
import { DiffBadgeComponent } from './components/diff-badge/diff-badge.component';
import { BalanceFormComponent, BalanceFormSubmission, HybridFormSubmission } from './components/balance-form/balance-form.component';
import { JsonImportDialogComponent } from './components/json-import-dialog/json-import-dialog.component';
import { TimelineChartComponent } from './components/timeline-chart/timeline-chart.component';

const LIVE_PATRIMONY_POLL_MS = 35_000;

@Component({
  selector: 'app-dashboard',
  imports: [
    EurCurrencyPipe,
    DecimalPipe,
    DonutChartComponent,
    DiffBadgeComponent,
    AssetSalesListDialogComponent,
    BalanceFormComponent,
    JsonImportDialogComponent,
    TimelineChartComponent,
  ],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
})
export class DashboardComponent {
  private readonly api = inject(FinanceApiService);
  private readonly investmentApi = inject(InvestmentApiService);
  private readonly marketPriceApi = inject(MarketPriceApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly periodStorage = inject(PeriodStorageService);
  private readonly destroyRef = inject(DestroyRef);
  private livePatrimonyPollSub: Subscription | null = null;

  readonly monthNames = MONTH_NAMES;

  readonly year = signal<number>(this.periodStorage.read().year);
  readonly month = signal<number>(this.periodStorage.read().month);

  readonly entities = signal<Entity[]>([]);
  readonly recordResponse = signal<MonthlyRecordResponse | null>(null);
  readonly loading = signal<boolean>(false);
  readonly saving = signal<boolean>(false);
  readonly updating = signal<boolean>(false);
  readonly deleting = signal<boolean>(false);
  readonly showDeleteConfirm = signal<boolean>(false);
  readonly importing = signal<boolean>(false);
  readonly showImportDialog = signal<boolean>(false);
  readonly showAssetSalesDialog = signal<boolean>(false);
  readonly assetSalesList = signal<AssetSalesListResponse | null>(null);
  readonly importErrorMessage = signal<string | null>(null);
  readonly errorMessage = signal<string | null>(null);
  readonly timelinePoints = signal<TimelinePoint[]>([]);
  readonly editing = signal<boolean>(false);

  readonly livePatrimonyMode = signal(false);
  readonly livePortfolioSummary = signal<LiveInvestmentSummary | null>(null);
  readonly livePatrimonyLoading = signal(false);

  readonly hasRecord = computed(() => this.recordResponse()?.exists === true);
  readonly hasFullRecord = computed(() => {
    const record = this.recordResponse()?.record;
    if (!record) {
      return false;
    }
    const simpleCount = this.entities().filter(
      (entity) => entity.entity_type === 'LIQUID' || entity.entity_type === 'INVESTED',
    ).length;
    if (simpleCount === 0) {
      return record.hybrid_accounts.length > 0;
    }
    return record.balances.length > 0;
  });
  readonly hasTimeline = computed(() => this.timelinePoints().length > 0);

  readonly isPastMonth = computed(() => {
    const now = new Date();
    const currentYear = now.getFullYear();
    const currentMonth = now.getMonth() + 1;
    return this.year() < currentYear || (this.year() === currentYear && this.month() < currentMonth);
  });

  readonly canImportJson = computed(() => this.isPastMonth() && !this.hasFullRecord());

  readonly displayInvestedEur = computed(() => {
    const liveSummary = this.livePortfolioSummary();
    if (this.livePatrimonyMode() && liveSummary?.hasData) {
      return liveSummary.marketValueEur;
    }
    return this.recordResponse()?.record?.total_invested ?? 0;
  });

  readonly displayNetWorthEur = computed(() => {
    const liquid = this.recordResponse()?.record?.total_liquid ?? 0;
    return this.round2(liquid + this.displayInvestedEur());
  });

  readonly donutInvestedLabel = computed(() =>
    this.livePatrimonyMode() ? 'Valor real invertido' : 'Invertido',
  );

  readonly livePatrimonyProfitEur = computed(() => {
    const liveSummary = this.livePortfolioSummary();
    if (!this.livePatrimonyMode() || !liveSummary?.hasData) {
      return null;
    }
    return liveSummary.profitEur;
  });

  readonly livePatrimonyProfitPct = computed(() => {
    const liveSummary = this.livePortfolioSummary();
    if (!this.livePatrimonyMode() || !liveSummary?.hasData) {
      return null;
    }
    return liveSummary.profitPct;
  });

  constructor() {
    this.destroyRef.onDestroy(() => this.stopLivePatrimonyPoll());
    // Reacciona a cambios de query params (navegación desde el shell global)
    this.route.queryParamMap.subscribe((params) => {
      const stored = this.periodStorage.read();
      const year = params.get('year') ? Number(params.get('year')) : stored.year;
      const month = params.get('month') ? Number(params.get('month')) : stored.month;

      const periodChanged = year !== this.year() || month !== this.month();
      this.year.set(year);
      this.month.set(month);
      this.periodStorage.save(year, month);
      this.editing.set(false);
      this.livePatrimonyMode.set(false);
      this.livePortfolioSummary.set(null);
      this.stopLivePatrimonyPoll();

      if (periodChanged || !this.recordResponse()) {
        this.loadRecord();
      }
    });

    this.loadEntities();
    this.loadTimeline();
    this.loadAssetSales();
  }

  private loadEntities(): void {
    this.api.getActiveEntities().subscribe({
      next: (entities) => this.entities.set(entities),
      error: () => this.errorMessage.set('No se pudieron cargar las entidades.'),
    });
  }

  liveProfitClass(profit: number | null): string {
    if (profit === null || profit === 0) {
      return 'live-patrimony-balance live-patrimony-balance--neutral';
    }
    return profit > 0
      ? 'live-patrimony-balance live-patrimony-balance--gain'
      : 'live-patrimony-balance live-patrimony-balance--loss';
  }

  toggleLivePatrimony(): void {
    const willEnable = !this.livePatrimonyMode();
    this.livePatrimonyMode.set(willEnable);
    if (willEnable) {
      this.refreshLivePatrimony();
      this.startLivePatrimonyPoll();
      return;
    }
    this.stopLivePatrimonyPoll();
    this.livePortfolioSummary.set(null);
  }

  private startLivePatrimonyPoll(): void {
    this.stopLivePatrimonyPoll();
    this.livePatrimonyPollSub = timer(LIVE_PATRIMONY_POLL_MS, LIVE_PATRIMONY_POLL_MS)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        if (this.livePatrimonyMode()) {
          this.refreshLivePatrimony();
        }
      });
  }

  private stopLivePatrimonyPoll(): void {
    this.livePatrimonyPollSub?.unsubscribe();
    this.livePatrimonyPollSub = null;
  }

  private refreshLivePatrimony(): void {
    if (!this.hasFullRecord()) {
      return;
    }

    this.livePatrimonyLoading.set(true);
    const year = this.year();
    const month = this.month();

    this.investmentApi
      .getOverview(year, month)
      .pipe(
        switchMap((overview) => {
          const categoryIds = overview.categories.map((cat) => cat.category_id);
          if (categoryIds.length === 0) {
            return of<{
              overview: InvestmentOverviewResponse;
              details: CategoryDetailResponse[];
              prices: MarketPriceResponse[];
            }>({
              overview,
              details: [],
              prices: [],
            });
          }
          return forkJoin({
            overview: of(overview),
            details: forkJoin(
              categoryIds.map((categoryId) =>
                this.investmentApi.getCategoryDetail(year, month, categoryId),
              ),
            ),
            prices: this.marketPriceApi.getMarketPrices().pipe(catchError(() => of([]))),
          });
        }),
        catchError(
          () =>
            of<{
              overview: InvestmentOverviewResponse;
              details: CategoryDetailResponse[];
              prices: MarketPriceResponse[];
            } | null>(null),
        ),
      )
      .subscribe((payload) => {
        this.livePatrimonyLoading.set(false);
        if (!payload || !this.livePatrimonyMode()) {
          return;
        }
        const summary = computePortfolioLiveSummaryFromDetails(
          payload.overview.categories.map((cat) => ({
            categoryId: cat.category_id,
            investedEur: cat.amount_eur,
          })),
          payload.details,
          marketPricesToMap(payload.prices),
          payload.overview.total_invested,
        );
        this.livePortfolioSummary.set(summary.hasData ? summary : null);
      });
  }

  private round2(value: number): number {
    return round2(value);
  }

  private loadRecord(): void {
    this.loading.set(true);
    this.errorMessage.set(null);
    this.api.getMonthlyRecord(this.year(), this.month()).subscribe({
      next: (response) => {
        this.recordResponse.set(response);
        this.loading.set(false);
      },
      error: () => {
        this.recordResponse.set(null);
        this.loading.set(false);
        this.errorMessage.set(
          'No se pudo conectar con la API. Comprueba que el backend está arrancado.',
        );
      },
    });
  }

  private loadAssetSales(): void {
    this.investmentApi.getAssetSalesList().subscribe({
      next: (response) => this.assetSalesList.set(response),
      error: () => this.assetSalesList.set(null),
    });
  }

  openAssetSalesDialog(): void {
    this.showAssetSalesDialog.set(true);
  }

  closeAssetSalesDialog(): void {
    this.showAssetSalesDialog.set(false);
  }

  private loadTimeline(): void {
    this.api.getTimeline().subscribe({
      next: (response) => this.timelinePoints.set(response.points),
      error: () => this.timelinePoints.set([]),
    });
  }

  private refreshAfterSave(): void {
    this.loadTimeline();
  }

  onSaveMonth(submission: BalanceFormSubmission): void {
    this.applyPartialSave(submission, this.editing());
  }

  private hybridChanged(
    hybrid: HybridBalanceImport,
    previous: { liquid_amount: number; cumulative_invested: number } | undefined,
  ): boolean {
    if (previous === undefined) {
      return true;
    }
    const invested = hybrid.invested_amount ?? 0;
    return previous.liquid_amount !== hybrid.liquid_amount || previous.cumulative_invested !== invested;
  }

  private applyPartialSave(submission: BalanceFormSubmission, editMode: boolean): void {
    const initial = this.recordResponse()?.record;
    const year = this.year();
    const month = this.month();

    let balancesToPatch = submission.balances;
    let hybridsToPatch = submission.hybridBalances;

    if (editMode && initial) {
      balancesToPatch = submission.balances.filter((balance) => {
        const previous = initial.balances.find((row) => row.entity_id === balance.entity_id);
        return previous === undefined || previous.balance_amount !== balance.balance_amount;
      });
      hybridsToPatch = submission.hybridBalances.filter((hybrid) => {
        const previous = initial.hybrid_accounts.find((row) => row.entity_id === hybrid.entity_id);
        return this.hybridChanged(hybrid, previous);
      });
    } else if (initial?.hybrid_accounts.length) {
      hybridsToPatch = submission.hybridBalances.filter((hybrid) => {
        const previous = initial.hybrid_accounts.find((row) => row.entity_id === hybrid.entity_id);
        return this.hybridChanged(hybrid, previous);
      });
    }

    if (balancesToPatch.length === 0 && hybridsToPatch.length === 0) {
      this.editing.set(false);
      return;
    }

    this.saving.set(true);
    this.errorMessage.set(null);

    const calls: Observable<MonthlyRecordResponse>[] = [];
    if (balancesToPatch.length > 0) {
      calls.push(this.api.patchEntityBalances(year, month, balancesToPatch));
    }
    if (hybridsToPatch.length > 0) {
      calls.push(this.api.patchHybridBalances(year, month, hybridsToPatch));
    }

    const request: Observable<MonthlyRecordResponse | MonthlyRecordResponse[]> =
      calls.length === 1 ? calls[0] : forkJoin(calls);

    request.subscribe({
      next: (response: MonthlyRecordResponse | MonthlyRecordResponse[]) => {
        const latest = Array.isArray(response) ? response[response.length - 1] : response;
        this.recordResponse.set(latest);
        this.saving.set(false);
        this.editing.set(false);
        this.refreshAfterSave();
      },
      error: (err: unknown) => {
        this.saving.set(false);
        this.errorMessage.set(this.extractSaveError(err));
      },
    });
  }

  private extractSaveError(err: unknown): string {
    const httpError = err as { error?: { detail?: string } };
    if (typeof httpError.error?.detail === 'string') {
      return httpError.error.detail;
    }
    return 'No se pudo guardar los cambios. Inténtalo de nuevo.';
  }

  onUpdateHybrids(submission: HybridFormSubmission): void {
    this.updating.set(true);
    this.errorMessage.set(null);
    this.api.patchHybridBalances(this.year(), this.month(), submission.hybridBalances).subscribe({
      next: (response) => {
        this.recordResponse.set(response);
        this.updating.set(false);
      },
      error: () => {
        this.updating.set(false);
        this.errorMessage.set('No se pudieron guardar las híbridas. Inténtalo de nuevo.');
      },
    });
  }

  openEditMode(): void {
    this.editing.set(true);
    this.errorMessage.set(null);
  }

  closeEditMode(): void {
    this.editing.set(false);
  }

  openDeleteConfirm(): void {
    this.showDeleteConfirm.set(true);
  }

  closeDeleteConfirm(): void {
    this.showDeleteConfirm.set(false);
  }

  confirmDeleteMonth(): void {
    this.deleting.set(true);
    this.errorMessage.set(null);
    this.api.deleteMonthlyRecord(this.year(), this.month()).subscribe({
      next: () => {
        this.deleting.set(false);
        this.showDeleteConfirm.set(false);
        this.loadRecord();
        this.loadTimeline();
      },
      error: () => {
        this.deleting.set(false);
        this.errorMessage.set('No se pudo eliminar el mes. Inténtalo de nuevo.');
      },
    });
  }

  openImportDialog(): void {
    this.importErrorMessage.set(null);
    this.showImportDialog.set(true);
  }

  closeImportDialog(): void {
    this.showImportDialog.set(false);
    this.importErrorMessage.set(null);
  }

  onImportJson(payload: ImportPayload): void {
    this.importing.set(true);
    this.importErrorMessage.set(null);
    this.errorMessage.set(null);

    this.api.importMonthlyRecord(this.year(), this.month(), payload).subscribe({
      next: (response) => {
        this.recordResponse.set(response);
        this.importing.set(false);
        this.showImportDialog.set(false);
        this.refreshAfterSave();
      },
      error: (err) => {
        this.importing.set(false);
        this.importErrorMessage.set(this.extractImportError(err));
      },
    });
  }

  private extractImportError(err: unknown): string {
    const httpError = err as { error?: { detail?: string | { message?: string; mismatches?: string[] } } };
    const detail = httpError.error?.detail;

    if (typeof detail === 'string') {
      return detail;
    }

    if (detail && typeof detail === 'object') {
      const mismatches = detail.mismatches?.join(' · ');
      return mismatches ? `${detail.message ?? 'Error de validación'}: ${mismatches}` : 'No se pudo importar el JSON.';
    }

    return 'No se pudo importar el JSON. Revisa el payload y los totales.';
  }
}
