import { CurrencyPipe, DatePipe, DecimalPipe } from '@angular/common';
import { Component, input } from '@angular/core';

import { AssetGroup, EntityGroup } from '../../core/models/ledger.model';

/**
 * Vista de "libro mayor" de inversiones: replica el Excel de seguimiento,
 * agrupado estrictamente por entidad financiera → aportaciones fiat → activos.
 *
 * Componente puramente presentacional: recibe los datos ya agregados por el
 * backend y solo se encarga del renderizado (tablas + formato).
 */
@Component({
  selector: 'app-investment-ledger',
  imports: [CurrencyPipe, DecimalPipe, DatePipe],
  templateUrl: './investment-ledger.component.html',
  styleUrl: './investment-ledger.component.scss',
})
export class InvestmentLedgerComponent {
  readonly entities = input.required<EntityGroup[]>();

  hasFiatDeposits(entity: EntityGroup): boolean {
    return !!entity.fiat_deposits && entity.fiat_deposits.length > 0;
  }

  hasTransactions(asset: AssetGroup): boolean {
    return asset.transactions.length > 0;
  }

  profitClass(value: number | null): string {
    if (value === null) {
      return 'text-slate-500';
    }
    return value >= 0 ? 'text-emerald-400' : 'text-rose-400';
  }
}
