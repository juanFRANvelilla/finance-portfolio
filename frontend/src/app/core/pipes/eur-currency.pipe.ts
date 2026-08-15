import { Pipe, PipeTransform } from '@angular/core';

@Pipe({ name: 'eurCurrency' })
export class EurCurrencyPipe implements PipeTransform {
  private readonly formatter = new Intl.NumberFormat('es-ES', {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: 2,
  });

  transform(value: number | null | undefined): string {
    if (value === null || value === undefined || Number.isNaN(value)) {
      return '—';
    }
    return this.formatter.format(value);
  }
}
