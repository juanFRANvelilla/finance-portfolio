import { Component, computed, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { Entity } from '../../../../core/models/entity.model';
import { EntityBalanceInput } from '../../../../core/models/monthly-record.model';

@Component({
  selector: 'app-balance-form',
  imports: [FormsModule],
  templateUrl: './balance-form.component.html',
})
export class BalanceFormComponent {
  readonly entities = input.required<Entity[]>();
  readonly saving = input<boolean>(false);
  readonly save = output<EntityBalanceInput[]>();

  /**
   * Las entidades HYBRID todavia no se gestionan (dependen de
   * monthly_hybrid_accounts, fuera de alcance por ahora), asi que solo se
   * piden saldos de entidades simples: LIQUID e INVESTED.
   */
  readonly simpleEntities = computed(() =>
    this.entities().filter((e) => e.entity_type === 'LIQUID' || e.entity_type === 'INVESTED'),
  );

  readonly values = signal<Record<string, number | null>>({});

  onValueChange(entityId: string, value: string): void {
    const parsed = value === '' ? null : Number(value);
    this.values.update((current) => ({ ...current, [entityId]: parsed }));
  }

  onSubmit(): void {
    const balances: EntityBalanceInput[] = this.simpleEntities().map((entity) => ({
      entity_id: entity.id,
      balance_amount: this.values()[entity.id] ?? 0,
    }));
    this.save.emit(balances);
  }
}
