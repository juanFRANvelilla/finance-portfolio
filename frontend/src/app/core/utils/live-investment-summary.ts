import { AssetInvestmentDetail } from '../models/investment.model';

export interface LiveInvestmentSummary {
  marketValueEur: number;
  profitEur: number;
  profitPct: number;
  assetCount: number;
  hasData: boolean;
}

export interface LivePriceQuote {
  price: number;
  currency: string;
}

export type LivePriceByAssetId = ReadonlyMap<string, LivePriceQuote>;

/** Datos de una categoría para calcular valor de mercado y balance del panel ℹ️. */
export interface CategoryLiveSummaryInput {
  investedEur: number;
  othersAmountEur: number;
  assets: readonly AssetInvestmentDetail[];
  fxUsdToEur: number;
}

export function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

export function amountToEur(amount: number, currency: string, fxRate: number): number {
  if (currency === 'EUR') {
    return amount;
  }
  if (currency === 'USD' || currency === 'USDT') {
    return round2(amount * fxRate);
  }
  return amount;
}

export function assetMarketValueEur(
  asset: Pick<AssetInvestmentDetail, 'asset_type_id' | 'units' | 'amount_eur'>,
  fxUsdToEur: number,
  prices: LivePriceByAssetId,
): number | null {
  const live = prices.get(asset.asset_type_id);
  const units = asset.units;
  if (!live || units === null || units <= 0) {
    return null;
  }
  return round2(units * amountToEur(live.price, live.currency, fxUsdToEur));
}

export function assetPortfolioValueEur(
  asset: Pick<AssetInvestmentDetail, 'asset_type_id' | 'units' | 'amount_eur'>,
  fxUsdToEur: number,
  prices: LivePriceByAssetId,
): number {
  const liveMarket = assetMarketValueEur(asset, fxUsdToEur, prices);
  return liveMarket !== null ? liveMarket : asset.amount_eur;
}

export function computeCategoryLiveSummary(
  input: CategoryLiveSummaryInput,
  prices: LivePriceByAssetId,
): LiveInvestmentSummary {
  let totalMarketEur = input.othersAmountEur;
  let assetCount = 0;

  for (const asset of input.assets) {
    totalMarketEur += assetPortfolioValueEur(asset, input.fxUsdToEur, prices);
    assetCount += 1;
  }

  const marketValueEur = round2(totalMarketEur);
  const profitEur = round2(marketValueEur - input.investedEur);
  const profitPct =
    input.investedEur > 0 ? round2((profitEur / input.investedEur) * 100) : 0;

  return { marketValueEur, profitEur, profitPct, assetCount, hasData: true };
}

const EMPTY_SUMMARY: LiveInvestmentSummary = {
  marketValueEur: 0,
  profitEur: 0,
  profitPct: 0,
  assetCount: 0,
  hasData: false,
};

/**
 * Agrega los resúmenes ℹ️ de cada categoría en el total de cartera.
 * El valor de mercado y el balance del info general son la suma de los de cada categoría.
 */
export function aggregatePortfolioLiveSummary(
  categorySummaries: readonly LiveInvestmentSummary[],
  totalInvestedEur: number,
): LiveInvestmentSummary {
  if (categorySummaries.length === 0) {
    return { ...EMPTY_SUMMARY };
  }
  if (!categorySummaries.every((summary) => summary.hasData)) {
    return { ...EMPTY_SUMMARY };
  }

  const marketValueEur = round2(
    categorySummaries.reduce((acc, summary) => acc + summary.marketValueEur, 0),
  );
  const profitEur = round2(
    categorySummaries.reduce((acc, summary) => acc + summary.profitEur, 0),
  );
  const assetCount = categorySummaries.reduce((acc, summary) => acc + summary.assetCount, 0);
  const profitPct =
    totalInvestedEur > 0 ? round2((profitEur / totalInvestedEur) * 100) : 0;

  return { marketValueEur, profitEur, profitPct, assetCount, hasData: true };
}

/** Comprueba que el total de cartera coincide con la suma de categorías (para tests). */
export function categorySummariesMatchPortfolioAggregate(
  categorySummaries: readonly LiveInvestmentSummary[],
  portfolio: LiveInvestmentSummary,
): boolean {
  if (!portfolio.hasData || !categorySummaries.every((s) => s.hasData)) {
    return false;
  }
  const sumMarket = round2(
    categorySummaries.reduce((acc, s) => acc + s.marketValueEur, 0),
  );
  const sumProfit = round2(categorySummaries.reduce((acc, s) => acc + s.profitEur, 0));
  return portfolio.marketValueEur === sumMarket && portfolio.profitEur === sumProfit;
}
