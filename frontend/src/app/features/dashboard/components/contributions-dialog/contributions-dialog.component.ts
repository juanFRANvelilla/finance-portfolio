import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, effect, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { Contribution, EntityContributionsResponse } from '../../../../core/models/contribution.model';
import { MONTH_NAMES } from '../../../../core/models/month-names';
import { FinanceApiService } from '../../../../core/services/finance-api.service';
import { EurCurrencyPipe } from '../../../../core/pipes/eur-currency.pipe';
import { parseDecimalInput } from '../../../../core/utils/parse-decimal';

@Component({
  selector: 'app-contributions-dialog',
  imports: [FormsModule, DatePipe, DecimalPipe, EurCurrencyPipe],
  templateUrl: './contributions-dialog.component.html',
})
export class ContributionsDialogComponent {
  private readonly api = inject(FinanceApiService);

  readonly open = input.required<boolean>();
  readonly year = input.required<number>();
  readonly month = input.required<number>();
  readonly entityId = input.required<string>();
  readonly entityName = input.required<string>();
  readonly liquidAmount = input<number>(0);

  readonly close = output<void>();
  readonly changed = output<EntityContributionsResponse>();

  readonly monthNames = MONTH_NAMES;
  readonly loading = signal(false);
  readonly saving = signal(false);
  readonly errorMessage = signal<string | null>(null);
  readonly summary = signal<EntityContributionsResponse | null>(null);

  readonly newDate = signal('');
  readonly newAmount = signal('');
  readonly newNotes = signal('');

  constructor() {
    effect(() => {
      if (this.open()) {
        this.resetForm();
        this.loadContributions();
      }
    });

    effect(() => {
      if (this.open()) {
        this.liquidAmount();
        this.loadContributions();
      }
    });
  }

  private resetForm(): void {
    const today = new Date();
    const y = this.year();
    const m = this.month();
    const day = today.getFullYear() === y && today.getMonth() + 1 === m ? today.getDate() : 1;
    this.newDate.set(`${y}-${String(m).padStart(2, '0')}-${String(day).padStart(2, '0')}`);
    this.newAmount.set('');
    this.newNotes.set('');
    this.errorMessage.set(null);
  }

  loadContributions(): void {
    if (!this.open()) return;
    this.loading.set(true);
    this.errorMessage.set(null);
    this.api.getEntityContributions(this.year(), this.month(), this.entityId(), this.liquidAmount()).subscribe({
      next: (response) => {
        this.summary.set(response);
        this.loading.set(false);
        this.changed.emit(response);
      },
      error: () => {
        this.loading.set(false);
        this.errorMessage.set('No se pudieron cargar las aportaciones.');
      },
    });
  }

  addContribution(): void {
    const amount = parseDecimalInput(this.newAmount());
    if (amount === null || amount === 0) {
      this.errorMessage.set('Introduce un importe distinto de cero (positivo o negativo).');
      return;
    }
    if (!this.newDate()) {
      this.errorMessage.set('Introduce una fecha.');
      return;
    }

    this.saving.set(true);
    this.errorMessage.set(null);
    this.api
      .createEntityContribution(this.year(), this.month(), this.entityId(), {
        contribution_date: this.newDate(),
        amount,
        notes: this.newNotes().trim() || null,
      })
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.newAmount.set('');
          this.newNotes.set('');
          this.loadContributions();
        },
        error: (err) => {
          this.saving.set(false);
          const httpError = err as { error?: { detail?: string } };
          this.errorMessage.set(httpError?.error?.detail ?? 'No se pudo guardar la aportación.');
        },
      });
  }

  deleteContribution(row: Contribution): void {
    this.api.deleteEntityContribution(row.id).subscribe({
      next: () => this.loadContributions(),
      error: () => this.errorMessage.set('No se pudo eliminar la aportación.'),
    });
  }

  onClose(): void {
    this.close.emit();
  }
}
