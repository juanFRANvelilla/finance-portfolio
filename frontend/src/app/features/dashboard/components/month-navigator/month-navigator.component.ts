import { Component, computed, input, output } from '@angular/core';

import { MONTH_NAMES } from '../../../../core/models/month-names';

@Component({
  selector: 'app-month-navigator',
  templateUrl: './month-navigator.component.html',
})
export class MonthNavigatorComponent {
  readonly year = input.required<number>();
  readonly month = input.required<number>();
  readonly monthChange = output<{ year: number; month: number }>();

  /** El histórico de la app arranca en 2026, así que no se muestran años anteriores. */
  private static readonly MIN_YEAR = 2026;
  private static readonly YEARS_AHEAD = 9;

  readonly months = MONTH_NAMES;
  readonly years = computed(() => {
    const minYear = MonthNavigatorComponent.MIN_YEAR;
    const maxYear = Math.max(
      minYear + MonthNavigatorComponent.YEARS_AHEAD,
      this.year(),
    );
    const range: number[] = [];
    for (let y = minYear; y <= maxYear; y++) {
      range.push(y);
    }
    return range;
  });

  readonly isAtMinimum = computed(
    () => this.year() === MonthNavigatorComponent.MIN_YEAR && this.month() === 1,
  );

  previousMonth(): void {
    if (this.isAtMinimum()) {
      return;
    }
    let m = this.month() - 1;
    let y = this.year();
    if (m < 1) {
      m = 12;
      y -= 1;
    }
    this.monthChange.emit({ year: y, month: m });
  }

  nextMonth(): void {
    let m = this.month() + 1;
    let y = this.year();
    if (m > 12) {
      m = 1;
      y += 1;
    }
    this.monthChange.emit({ year: y, month: m });
  }

  onMonthSelect(month: number): void {
    this.monthChange.emit({ year: this.year(), month });
  }

  onYearSelect(year: number): void {
    this.monthChange.emit({ year, month: this.month() });
  }
}
