import { AssetSaleListItem } from '../models/investment.model';
import { round2 } from './live-investment-summary';

function yearMonthIndex(year: number, month: number): number {
  return year * 12 + (month - 1);
}

/** Venta en el mes de referencia o en un mes anterior (no futuras respecto al mes navegado). */
export function isSaleOnOrBeforeReference(
  saleYear: number,
  saleMonth: number,
  refYear: number,
  refMonth: number,
): boolean {
  return yearMonthIndex(saleYear, saleMonth) <= yearMonthIndex(refYear, refMonth);
}

export function isSaleAfterReference(
  saleYear: number,
  saleMonth: number,
  refYear: number,
  refMonth: number,
): boolean {
  return yearMonthIndex(saleYear, saleMonth) > yearMonthIndex(refYear, refMonth);
}

export function sumSalesProfitEurUpToReference(
  sales: readonly AssetSaleListItem[],
  refYear: number,
  refMonth: number,
): number {
  const total = sales
    .filter((s) => isSaleOnOrBeforeReference(s.sale_year, s.sale_month, refYear, refMonth))
    .reduce((acc, s) => acc + s.profit_eur, 0);
  return round2(total);
}
