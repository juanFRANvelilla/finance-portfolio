import { Component, computed, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { Entity } from '../../../../core/models/entity.model';
import { EntityBalanceInput, HybridBalanceImport } from '../../../../core/models/monthly-record.model';

export interface BalanceFormSubmission {
  balances: EntityBalanceInput[];
  hybridBalances: HybridBalanceImport[];
}

@Component({
  selector: 'app-balance-form',
  imports: [FormsModule],
  templateUrl: './balance-form.component.html',
})
export class BalanceFormComponent {
  readonly entities = input.required<Entity[]>();
  readonly saving = input<boolean>(false);
  readonly save = output<BalanceFormSubmission>();
  readonly importJson = output<void>();

  readonly simpleEntities = computed(() =>
    this.entities().filter((e) => e.entity_type === 'LIQUID' || e.entity_type === 'INVESTED'),
  );

  readonly hybridEntities = computed(() => this.entities().filter((e) => e.entity_type === 'HYBRID'));

  readonly values = signal<Record<string, number | null>>({});
  readonly hybridValues = signal<Record<string, { liquid: number | null; invested: number | null }>>({});

  onValueChange(entityId: string, value: string): void {
    const parsed = value === '' ? null : Number(value);
    this.values.update((current) => ({ ...current, [entityId]: parsed }));
  }

  onHybridValueChange(entityId: string, field: 'liquid' | 'invested', value: string): void {
    const parsed = value === '' ? null : Number(value);
    this.hybridValues.update((current) => {
      const existing = current[entityId] ?? { liquid: null, invested: null };
      return {
        ...current,
        [entityId]: {
          liquid: field === 'liquid' ? parsed : existing.liquid,
          invested: field === 'invested' ? parsed : existing.invested,
        },
      };
    });
  }

  onSubmit(): void {
    const balances: EntityBalanceInput[] = this.simpleEntities().map((entity) => ({
      entity_id: entity.id,
      balance_amount: this.values()[entity.id] ?? 0,
    }));

    const hybridBalances: HybridBalanceImport[] = this.hybridEntities().map((entity) => ({
      entity_id: entity.id,
      liquid_amount: this.hybridValues()[entity.id]?.liquid ?? 0,
      invested_amount: this.hybridValues()[entity.id]?.invested ?? 0,
    }));

    this.save.emit({ balances, hybridBalances });
  }
}
