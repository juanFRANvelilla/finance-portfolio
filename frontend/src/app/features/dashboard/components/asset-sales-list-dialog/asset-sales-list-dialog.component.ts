import { DecimalPipe } from '@angular/common';
import { Component, input, output } from '@angular/core';

import { AssetSaleListItem } from '../../../../core/models/investment.model';
import { MONTH_NAMES } from '../../../../core/models/month-names';
import { EurCurrencyPipe } from '../../../../core/pipes/eur-currency.pipe';
import { isSaleAfterReference } from '../../../../core/utils/asset-sales-period';

@Component({
  selector: 'app-asset-sales-list-dialog',
  imports: [DecimalPipe, EurCurrencyPipe],
  templateUrl: './asset-sales-list-dialog.component.html',
  styleUrl: './asset-sales-list-dialog.component.scss',
})
export class AssetSalesListDialogComponent {
  readonly open = input.required<boolean>();
  readonly sales = input<AssetSaleListItem[]>([]);
  readonly referenceYear = input.required<number>();
  readonly referenceMonth = input.required<number>();

  readonly close = output<void>();

  readonly monthNames = MONTH_NAMES;

  isFutureRelativeToReference(row: AssetSaleListItem): boolean {
    return isSaleAfterReference(row.sale_year, row.sale_month, this.referenceYear(), this.referenceMonth());
  }

  rowClass(row: AssetSaleListItem): string {
    if (this.isFutureRelativeToReference(row)) {
      return 'opacity-40';
    }
    return 'hover:bg-white/[0.02]';
  }

  profitClass(profit: number, row: AssetSaleListItem): string {
    if (this.isFutureRelativeToReference(row)) {
      return 'text-slate-600';
    }
    if (profit > 0) {
      return 'text-emerald-400';
    }
    if (profit < 0) {
      return 'text-rose-400';
    }
    return 'text-slate-300';
  }

  /** Equivalencia en € solo para importes en USD (en EUR ya se muestra el valor en euros). */
  showEurEquivalent(currency: string): boolean {
    return currency.trim().toUpperCase() === 'USD';
  }
}
