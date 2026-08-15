import { DecimalPipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';

import { FinanceApiService } from '../../core/services/finance-api.service';
import { Entity } from '../../core/models/entity.model';
import { EntityBalanceInput, MonthlyRecordResponse } from '../../core/models/monthly-record.model';
import { MONTH_NAMES } from '../../core/models/month-names';
import { EurCurrencyPipe } from '../../core/pipes/eur-currency.pipe';
import { MonthNavigatorComponent } from './components/month-navigator/month-navigator.component';
import { DonutChartComponent } from './components/donut-chart/donut-chart.component';
import { DiffBadgeComponent } from './components/diff-badge/diff-badge.component';
import { BalanceFormComponent } from './components/balance-form/balance-form.component';

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
  readonly errorMessage = signal<string | null>(null);

  readonly hasRecord = computed(() => this.recordResponse()?.exists === true);

  constructor() {
    this.loadEntities();
    this.loadRecord();
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
          'No se pudo conectar con la API. Comprueba que el backend está arrancado en http://localhost:8000.',
        );
      },
    });
  }

  onSaveMonth(balances: EntityBalanceInput[]): void {
    this.saving.set(true);
    this.errorMessage.set(null);
    this.api.upsertMonthlyRecord(this.year(), this.month(), { balances }).subscribe({
      next: (response) => {
        this.recordResponse.set(response);
        this.saving.set(false);
      },
      error: () => {
        this.saving.set(false);
        this.errorMessage.set('No se pudo guardar el mes. Inténtalo de nuevo.');
      },
    });
  }
}
