import { ElementRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { of } from 'rxjs';
import { describe, expect, it } from 'vitest';

import { AssetInvestmentDetail } from '../../core/models/investment.model';
import { InvestmentApiService } from '../../core/services/investment-api.service';
import { MarketPriceApiService } from '../../core/services/market-price-api.service';
import { PeriodStorageService } from '../../core/services/period-storage.service';
import { InvestmentDetailComponent } from './investment-detail.component';

describe('InvestmentDetailComponent - visibleAssetsFor', () => {
  function createComponent(): InvestmentDetailComponent {
    const mockInvestmentApi = {
      getOverview: () => of({ year: 2026, month: 2, total_invested: 0, categories: [] }),
      getCategoryDetail: () => of({ year: 2026, month: 2, category_id: 'cat-1', category_name: 'Fondos', is_computed: true, category_amount_eur: 0, fx_usd_to_eur: null, assets: [], allocated_amount_eur: 0, others_amount_eur: 0 }),
      saveCategoryAssets: () => of({}),
      updateAssetOrder: () => of({}),
      createAssetType: () => of({}),
      updateAssetType: () => of({}),
    };
    const mockMarketPriceApi = {
      getLivePrices: () => of([]),
    };
    const mockPeriodStorage = {
      read: () => ({ year: 2026, month: 2 }),
      save: () => {},
      write: () => {},
    };
    const mockActivatedRoute = {
      queryParamMap: of(convertToParamMap({})),
    };
    const mockElementRef = new ElementRef(document.createElement('div'));

    TestBed.configureTestingModule({
      providers: [
        InvestmentDetailComponent,
        { provide: InvestmentApiService, useValue: mockInvestmentApi },
        { provide: MarketPriceApiService, useValue: mockMarketPriceApi },
        { provide: PeriodStorageService, useValue: mockPeriodStorage },
        { provide: ActivatedRoute, useValue: mockActivatedRoute },
        { provide: ElementRef, useValue: mockElementRef },
      ],
    });

    return TestBed.inject(InvestmentDetailComponent);
  }

  function makeAsset(partial: Partial<AssetInvestmentDetail>): AssetInvestmentDetail {
    return {
      asset_type_id: 'asset-1',
      name: 'Test Asset',
      ticker: null,
      display_order: 1,
      currency: 'EUR',
      entity_id: null,
      entity_name: null,
      amount: 0,
      amount_eur: 0,
      units: null,
      has_transactions: false,
      ...partial,
    };
  }

  it('determines hasAssetInvestment correctly', () => {
    const comp = createComponent();

    // 0 amount and null units -> false
    expect(comp.hasAssetInvestment(makeAsset({ amount: 0, amount_eur: 0, units: null }))).toBe(false);

    // 0 amount and 0 units -> false
    expect(comp.hasAssetInvestment(makeAsset({ amount: 0, amount_eur: 0, units: 0 }))).toBe(false);

    // positive amount_eur -> true
    expect(comp.hasAssetInvestment(makeAsset({ amount: 50, amount_eur: 50, units: null }))).toBe(true);

    // positive units -> true
    expect(comp.hasAssetInvestment(makeAsset({ amount: 0, amount_eur: 0, units: 10 }))).toBe(true);
  });

  it('filters out assets with 0 invested amount and no units in visibleAssetsFor', () => {
    const comp = createComponent();

    const activeAsset = makeAsset({ asset_type_id: 'btc', name: 'Bitcoin', amount_eur: 500, units: 0.01 });
    const zeroAsset = makeAsset({ asset_type_id: 'ada', name: 'Cardano', amount_eur: 0, units: 0 });
    const zeroNullUnitsAsset = makeAsset({ asset_type_id: 'sol', name: 'Solana', amount_eur: 0, units: null });

    comp.panels.set({
      'cat-1': {
        open: true,
        loadingDetail: false,
        detail: {
          year: 2026,
          month: 2,
          category_id: 'cat-1',
          category_name: 'Cripto',
          is_computed: true,
          category_amount_eur: 500,
          fx_usd_to_eur: null,
          assets: [activeAsset, zeroAsset, zeroNullUnitsAsset],
          allocated_amount_eur: 500,
          others_amount_eur: 0,
        },
        errorMessage: null,
        assetEditMode: false,
        assetRows: [],
        fxUsdToEur: null,
        showAddAsset: false,
        newAssetName: '',
        newAssetTicker: '',
        newAssetCurrency: 'EUR',
        creatingAsset: false,
        assetOrderSnapshot: {},
        savingAssetOrder: false,
      },
    });

    const visible = comp.visibleAssetsFor('cat-1');
    expect(visible).toEqual([activeAsset]);
  });
});
