import { DecimalPipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';

import { FinanceApiService } from '../../core/services/finance-api.service';
import { Entity } from '../../core/models/entity.model';
import { EntityBalanceInput, ImportPayload, MonthlyRecordResponse, TimelinePoint } from '../../core/models/monthly-record.model';
import { MONTH_NAMES } from '../../core/models/month-names';
import { EurCurrencyPipe } from '../../core/pipes/eur-currency.pipe';
import { environment } from '../../../environments/environment';
import { MonthNavigatorComponent } from './components/month-navigator/month-navigator.component';
import { DonutChartComponent } from './components/donut-chart/donut-chart.component';
import { DiffBadgeComponent } from './components/diff-badge/diff-badge.component';
import { BalanceFormComponent } from './components/balance-form/balance-form.component';
import { JsonImportDialogComponent } from './components/json-import-dialog/json-import-dialog.component';
import { TimelineChartComponent } from './components/timeline-chart/timeline-chart.component';

const FIXED_DEFAULT_YEAR = 2026;

@Component({
  selector: 'app-dashboard',
  imports: [
    EurCurrencyPipe,
    DecimalPipe,
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

  readonly monthNames = MONTH_NAMES;

  readonly year = signal<number>(FIXED_DEFAULT_YEAR);
  readonly month = signal<number>(new Date().getMonth() + 1);

  readonly entities = signal<Entity[]>([]);
  readonly recordResponse = signal<MonthlyRecordResponse | null>(null);
  readonly loading = signal<boolean>(false);
  readonly saving = signal<boolean>(false);
  readonly importing = signal<boolean>(false);
  readonly showImportDialog = signal<boolean>(false);
  readonly importErrorMessage = signal<string | null>(null);
  readonly errorMessage = signal<string | null>(null);
  readonly timelinePoints = signal<TimelinePoint[]>([]);

  readonly hasRecord = computed(() => this.recordResponse()?.exists === true);
  readonly hasTimeline = computed(() => this.timelinePoints().length > 0);

  constructor() {
    this.loadEntities();
    this.loadRecord();
    this.loadTimeline();
  }

  onMonthChange(next: { year: number; month: number }): void {
    this.year.set(next.year);
    this.month.set(next.month);
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

  onSaveMonth(balances: EntityBalanceInput[]): void {
    this.saving.set(true);
    this.errorMessage.set(null);
    this.api.upsertMonthlyRecord(this.year(), this.month(), { balances }).subscribe({
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
