import { DecimalPipe } from '@angular/common';
import { Component, computed, input } from '@angular/core';

import { EurCurrencyPipe } from '../../../../core/pipes/eur-currency.pipe';

@Component({
  selector: 'app-diff-badge',
  imports: [EurCurrencyPipe, DecimalPipe],
  templateUrl: './diff-badge.component.html',
  styleUrl: './diff-badge.component.scss',
})
export class DiffBadgeComponent {
  readonly diff = input<number | null>(null);
  readonly investedDiff = input<number | null>(null);
  readonly previousNetWorth = input<number | null>(null);

  readonly isPositive = computed(() => (this.diff() ?? 0) >= 0);
  readonly isInvestedPositive = computed(() => (this.investedDiff() ?? 0) >= 0);
  readonly hasPrevious = computed(() => this.previousNetWorth() !== null);

  readonly percentageChange = computed(() => {
    const diff = this.diff();
    const previous = this.previousNetWorth();
    if (diff === null || previous === null || previous === 0) {
      return null;
    }
    return (diff / previous) * 100;
  });
}
