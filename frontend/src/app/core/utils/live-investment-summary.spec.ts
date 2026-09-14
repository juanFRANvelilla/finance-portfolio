import { describe, expect, it } from 'vitest';

import { AssetInvestmentDetail } from '../models/investment.model';
import {
  aggregatePortfolioLiveSummary,
  categorySummariesMatchPortfolioAggregate,
  computeCategoryLiveSummary,
  type CategoryLiveSummaryInput,
  type LiveInvestmentSummary,
  type LivePriceByAssetId,
} from './live-investment-summary';

function makeAsset(
  partial: Partial<AssetInvestmentDetail> & {
    asset_type_id: string;
    amount_eur: number;
  },
): AssetInvestmentDetail {
  return {
    name: partial.name ?? 'Activo',
    ticker: partial.ticker ?? null,
    currency: partial.currency ?? 'EUR',
    entity_id: null,
    entity_name: null,
    amount: partial.amount ?? partial.amount_eur,
    units: partial.units ?? null,
    previous_amount: null,
    previous_units: null,
    monthly_contribution: null,
    suggested_amount: null,
    suggested_units: null,
    has_transactions: false,
    ...partial,
  };
}

function summarizeAllCategories(
  categories: CategoryLiveSummaryInput[],
  prices: LivePriceByAssetId,
  totalInvestedEur: number,
) {
  const perCategory = categories.map((input) => computeCategoryLiveSummary(input, prices));
  const portfolio = aggregatePortfolioLiveSummary(perCategory, totalInvestedEur);
  return { perCategory, portfolio };
}

describe('live-investment-summary', () => {
  it('suma valor de mercado y balance de todas las categorías en el info general (fondos, acciones, crypto)', () => {
    const prices: LivePriceByAssetId = new Map([
      ['acc-msft', { price: 420, currency: 'USD' }],
      ['cry-btc', { price: 62_000, currency: 'USD' }],
    ]);

    const categories: CategoryLiveSummaryInput[] = [
      {
        investedEur: 8_000,
        othersAmountEur: 120,
        fxUsdToEur: 0.92,
        assets: [
          makeAsset({ asset_type_id: 'fund-1', amount_eur: 3_500, units: null }),
          makeAsset({ asset_type_id: 'fund-2', amount_eur: 4_380, units: null }),
        ],
      },
      {
        investedEur: 10_500,
        othersAmountEur: 0,
        fxUsdToEur: 0.92,
        assets: [
          makeAsset({
            asset_type_id: 'acc-msft',
            amount_eur: 5_000,
            amount: 5_434.78,
            currency: 'USD',
            units: 12,
          }),
          makeAsset({ asset_type_id: 'acc-etf', amount_eur: 5_500, units: null }),
        ],
      },
      {
        investedEur: 5_759.18,
        othersAmountEur: 40,
        fxUsdToEur: 0.92,
        assets: [
          makeAsset({
            asset_type_id: 'cry-btc',
            amount_eur: 4_000,
            amount: 4_000,
            currency: 'USD',
            units: 0.07,
          }),
          makeAsset({ asset_type_id: 'cry-eth', amount_eur: 1_719.18, units: null }),
        ],
      },
    ];

    const totalInvestedEur = categories.reduce((acc, cat) => acc + cat.investedEur, 0);
    const { perCategory, portfolio } = summarizeAllCategories(categories, prices, totalInvestedEur);

    expect(perCategory).toHaveLength(3);
    expect(categorySummariesMatchPortfolioAggregate(perCategory, portfolio)).toBe(true);

    const sumMarket = perCategory.reduce((acc, s) => acc + s.marketValueEur, 0);
    const sumBalance = perCategory.reduce((acc, s) => acc + s.profitEur, 0);
    expect(portfolio.marketValueEur).toBeCloseTo(sumMarket, 2);
    expect(portfolio.profitEur).toBeCloseTo(sumBalance, 2);
    expect(portfolio.profitEur).toBeCloseTo(portfolio.marketValueEur - totalInvestedEur, 2);
  });

  it('recorre cualquier número de categorías sin asumir solo tres tipos', () => {
    const prices: LivePriceByAssetId = new Map([
      ['a1', { price: 10, currency: 'EUR' }],
      ['a4', { price: 100, currency: 'EUR' }],
    ]);

    for (const categoryCount of [1, 2, 3, 4, 6]) {
      const categories: CategoryLiveSummaryInput[] = Array.from(
        { length: categoryCount },
        (_, index) => ({
          investedEur: 1_000 + index * 250,
          othersAmountEur: index * 10,
          fxUsdToEur: 1,
          assets: [
            makeAsset({
              asset_type_id: `a${index}`,
              amount_eur: 600 + index * 50,
              units: index % 2 === 0 ? 5 : null,
            }),
            makeAsset({
              asset_type_id: `b${index}`,
              amount_eur: 300,
              units: null,
            }),
          ],
        }),
      );

      const totalInvestedEur = categories.reduce((acc, cat) => acc + cat.investedEur, 0);
      const { perCategory, portfolio } = summarizeAllCategories(categories, prices, totalInvestedEur);

      expect(perCategory).toHaveLength(categoryCount);
      expect(categorySummariesMatchPortfolioAggregate(perCategory, portfolio)).toBe(true);
    }
  });

  it('devuelve hasData false en cartera si falta alguna categoría', () => {
    const emptyCategory: LiveInvestmentSummary = {
      marketValueEur: 0,
      profitEur: 0,
      profitPct: 0,
      assetCount: 0,
      hasData: false,
    };
    const ready: LiveInvestmentSummary = {
      marketValueEur: 100,
      profitEur: 5,
      profitPct: 5,
      assetCount: 1,
      hasData: true,
    };

    expect(aggregatePortfolioLiveSummary([ready, emptyCategory], 200).hasData).toBe(false);
    expect(aggregatePortfolioLiveSummary([ready, ready], 200).hasData).toBe(true);
  });
});
