import { DecimalPipe } from '@angular/common';
import { Component, input, output } from '@angular/core';

import { AssetSaleListItem } from '../../../../core/models/investment.model';
import { MONTH_NAMES } from '../../../../core/models/month-names';
import { EurCurrencyPipe } from '../../../../core/pipes/eur-currency.pipe';

@Component({
  selector: 'app-asset-sales-list-dialog',
  imports: [DecimalPipe, EurCurrencyPipe],
  templateUrl: './asset-sales-list-dialog.component.html',
  styleUrl: './asset-sales-list-dialog.component.scss',
})
export class AssetSalesListDialogComponent {
  readonly open = input.required<boolean>();
  readonly sales = input<AssetSaleListItem[]>([]);

  readonly close = output<void>();

  readonly monthNames = MONTH_NAMES;

  profitClass(profit: number): string {
    if (profit > 0) {
      return 'text-emerald-400';
    }
    if (profit < 0) {
      return 'text-rose-400';
    }
    return 'text-slate-300';
  }
}
