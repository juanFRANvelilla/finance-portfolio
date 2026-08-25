import { DecimalPipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { FinanceApiService } from '../../core/services/finance-api.service';
import { PeriodStorageService } from '../../core/services/period-storage.service';
import { Entity } from '../../core/models/entity.model';
import { ImportPayload, MonthlyRecordResponse, TimelinePoint } from '../../core/models/monthly-record.model';
import { MONTH_NAMES } from '../../core/models/month-names';
import { EurCurrencyPipe } from '../../core/pipes/eur-currency.pipe';
import { environment } from '../../../environments/environment';
import { MonthNavigatorComponent } from './components/month-navigator/month-navigator.component';
import { DonutChartComponent } from './components/donut-chart/donut-chart.component';
import { DiffBadgeComponent } from './components/diff-badge/diff-badge.component';
import { BalanceFormComponent, BalanceFormSubmission } from './components/balance-form/balance-form.component';
import { JsonImportDialogComponent } from './components/json-import-dialog/json-import-dialog.component';
import { TimelineChartComponent } from './components/timeline-chart/timeline-chart.component';

@Component({
  selector: 'app-dashboard',
  imports: [
    EurCurrencyPipe,
    DecimalPipe,
    RouterLink,
    MonthNavigatorComponent,
    DonutChartComponent,
    DiffBadgeComponent,
    BalanceFormComponent,
    JsonImportDialogComponent,
    TimelineChartComponent,
  ],
  templateUrl: './dashboard.component.html',
})
export class DashboardComponent {
  private readonly api = inject(FinanceApiService);
  private readonly periodStorage = inject(PeriodStorageService);
  private readonly storedPeriod = this.periodStorage.read();

  readonly monthNames = MONTH_NAMES;

  readonly year = signal<number>(this.storedPeriod.year);
  readonly month = signal<number>(this.storedPeriod.month);

  readonly entities = signal<Entity[]>([]);
  readonly recordResponse = signal<MonthlyRecordResponse | null>(null);
  readonly loading = signal<boolean>(false);
  readonly saving = signal<boolean>(false);
  readonly deleting = signal<boolean>(false);
  readonly showDeleteConfirm = signal<boolean>(false);
  readonly importing = signal<boolean>(false);
  readonly showImportDialog = signal<boolean>(false);
  readonly importErrorMessage = signal<string | null>(null);
  readonly errorMessage = signal<string | null>(null);
  readonly timelinePoints = signal<TimelinePoint[]>([]);

  readonly hasRecord = computed(() => this.recordResponse()?.exists === true);
  readonly hasTimeline = computed(() => this.timelinePoints().length > 0);

  /** Solo se puede importar JSON histórico para meses ya cerrados (anteriores al mes actual real). */
  readonly isPastMonth = computed(() => {
    const now = new Date();
    const currentYear = now.getFullYear();
    const currentMonth = now.getMonth() + 1;
    return this.year() < currentYear || (this.year() === currentYear && this.month() < currentMonth);
  });

  readonly canImportJson = computed(() => this.isPastMonth() && !this.hasRecord());

  constructor() {
    this.loadEntities();
    this.loadRecord();
    this.loadTimeline();
  }

  onMonthChange(next: { year: number; month: number }): void {
    this.year.set(next.year);
    this.month.set(next.month);
    this.periodStorage.save(next.year, next.month);
    this.loadRecord();
  }

  private loadEntities(): void {
    this.api.getActiveEntities().subscribe({
      next: (entities) => this.entities.set(entities),
      error: () => this.errorMessage.set('No se pudieron cargar las entidades.'),
    });
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
          `No se pudo conectar con la API. Comprueba que el backend está arrancado en ${environment.apiUrl.replace('/api', '')}.`,
        );
      },
    });
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
    this.saving.set(true);
    this.errorMessage.set(null);
    this.api
      .upsertMonthlyRecord(this.year(), this.month(), {
        balances: submission.balances,
        hybrid_balances: submission.hybridBalances,
      })
      .subscribe({
        next: (response) => {
          this.recordResponse.set(response);
          this.saving.set(false);
          this.refreshAfterSave();
        },
        error: () => {
          this.saving.set(false);
          this.errorMessage.set('No se pudo guardar el mes. Inténtalo de nuevo.');
        },
      });
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
