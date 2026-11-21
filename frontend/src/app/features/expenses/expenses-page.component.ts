import { DecimalPipe } from '@angular/common';
import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';

import { MonthlyExpensesResponse } from '../../core/models/expense.model';
import { MONTH_NAMES } from '../../core/models/month-names';
import { EurCurrencyPipe } from '../../core/pipes/eur-currency.pipe';
import { FinanceApiService } from '../../core/services/finance-api.service';
import { PeriodStorageService } from '../../core/services/period-storage.service';
import {
  DonutSegment,
  SegmentDonutChartComponent,
} from '../../shared/components/segment-donut-chart/segment-donut-chart.component';

@Component({
  selector: 'app-expenses-page',
  imports: [EurCurrencyPipe, DecimalPipe, SegmentDonutChartComponent],
  templateUrl: './expenses-page.component.html',
  styleUrl: './expenses-page.component.scss',
})
export class ExpensesPageComponent implements OnInit {
  private readonly api = inject(FinanceApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly periodStorage = inject(PeriodStorageService);

  private readonly storedPeriod = this.periodStorage.read();
  readonly year = signal<number>(this.storedPeriod.year);
  readonly month = signal<number>(this.storedPeriod.month);

  readonly loading = signal<boolean>(false);
  readonly importing = signal<boolean>(false);
  readonly isDraggingOver = signal<boolean>(false);
  private dragCounter = 0;

  readonly errorMessage = signal<string | null>(null);
  readonly importMessage = signal<string | null>(null);
  readonly importFailed = signal<boolean>(false);
  readonly expenses = signal<MonthlyExpensesResponse | null>(null);
  readonly expandedCategories = signal<Set<string>>(new Set<string>());

  readonly monthNames = MONTH_NAMES;

  readonly monthLabel = computed(() => {
    const m = this.month();
    const y = this.year();
    if (m >= 1 && m <= 12) {
      return `${this.monthNames[m - 1]} ${y}`;
    }
    return `${m}/${y}`;
  });

  readonly hasExpenses = computed(() => {
    const exp = this.expenses();
    return !!exp && exp.has_expenses;
  });

  readonly donutSegments = computed<DonutSegment[]>(() => {
    const exp = this.expenses();
    if (!exp || !exp.categories || exp.categories.length === 0) {
      return [];
    }
    return exp.categories.map((c) => ({
      id: c.category,
      label: c.category_name,
      value: c.amount,
      color: c.color,
    }));
  });

  ngOnInit(): void {
    this.route.queryParamMap.subscribe((params) => {
      const year = Number(params.get('year'));
      const month = Number(params.get('month'));
      if (year && month) {
        this.year.set(year);
        this.month.set(month);
      }
      this.load();
    });
  }

  load(): void {
    this.loading.set(true);
    this.errorMessage.set(null);
    this.api.getMonthlyExpenses(this.year(), this.month()).subscribe({
      next: (data) => {
        this.expenses.set(data);
        this.loading.set(false);
      },
      error: () => {
        this.errorMessage.set('No se pudieron cargar los gastos del mes.');
        this.loading.set(false);
      },
    });
  }

  toggleCategory(category: string): void {
    const next = new Set(this.expandedCategories());
    if (next.has(category)) {
      next.delete(category);
    } else {
      next.add(category);
    }
    this.expandedCategories.set(next);
  }

  isExpanded(category: string): boolean {
    return this.expandedCategories().has(category);
  }

  onDragEnter(e: DragEvent): void {
    e.preventDefault();
    e.stopPropagation();
    this.dragCounter++;
    this.isDraggingOver.set(true);
  }

  onDragOver(e: DragEvent): void {
    e.preventDefault();
    e.stopPropagation();
  }

  onDragLeave(e: DragEvent): void {
    e.preventDefault();
    e.stopPropagation();
    this.dragCounter--;
    if (this.dragCounter <= 0) {
      this.dragCounter = 0;
      this.isDraggingOver.set(false);
    }
  }

  onDrop(e: DragEvent): void {
    e.preventDefault();
    e.stopPropagation();
    this.dragCounter = 0;
    this.isDraggingOver.set(false);

    const files = e.dataTransfer?.files;
    if (files && files.length > 0) {
      this.processFiles(Array.from(files));
    }
  }

  onFilesSelected(target: HTMLInputElement): void {
    const files = target.files;
    if (files && files.length > 0) {
      this.processFiles(Array.from(files));
      target.value = '';
    }
  }

  processFiles(files: File[]): void {
    const validFiles = files.filter(
      (f) => f.name.toLowerCase().endsWith('.xls') || f.name.toLowerCase().endsWith('.xlsx'),
    );
    if (validFiles.length === 0) {
      this.importFailed.set(true);
      this.importMessage.set('Por favor, selecciona o arrastra ficheros válidos de Excel (.xls o .xlsx).');
      return;
    }

    this.importing.set(true);
    this.importMessage.set(null);
    this.importFailed.set(false);

    this.api.importExpenses(this.year(), this.month(), validFiles).subscribe({
      next: (res) => {
        this.importing.set(false);
        this.expenses.set(res);

        const parts: string[] = [];
        if (res.imported_months?.length) {
          const sources = res.imported_sources?.length
            ? ` [${res.imported_sources.join(' + ')}]`
            : '';
          parts.push(`Gastos importados para: ${res.imported_months.join(', ')}${sources}.`);
        }
        if (res.skipped_months?.length) {
          parts.push(`Meses omitidos por ya tener registros previos: ${res.skipped_months.join(', ')}.`);
        }
        if (parts.length === 0) {
          parts.push('Los meses detectados ya disponían de registros y se han omitido para no sobrescribir.');
        }

        this.importMessage.set(parts.join(' '));
      },
      error: (err) => {
        this.importing.set(false);
        this.importFailed.set(true);
        this.importMessage.set(
          err?.error?.detail || 'No se pudieron importar los extractos de gastos.',
        );
      },
    });
  }

  deleteMonth(): void {
    const label = this.monthLabel();
    if (!confirm(`¿Deseas eliminar todos los gastos registrados en ${label} para poder volver a importarlos?`)) {
      return;
    }
    this.loading.set(true);
    this.api.deleteMonthlyExpenses(this.year(), this.month()).subscribe({
      next: () => {
        this.importMessage.set(`Gastos de ${label} eliminados.`);
        this.importFailed.set(false);
        this.load();
      },
      error: () => {
        this.loading.set(false);
        this.errorMessage.set(`No se pudieron eliminar los gastos de ${label}.`);
      },
    });
  }
}
