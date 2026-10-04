import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  AssetInvestmentsUpsert,
  AssetType,
  AssetTypeCreate,
  AssetTypeUpdate,
  CategoryAssetDisplayOrderUpdate,
  CategoryDetailResponse,
  InvestmentCategory,
  InvestmentOverviewResponse,
  AssetSaleContextResponse,
  AssetSaleCreate,
  AssetSaleRead,
  AssetSalesListResponse,
} from '../models/investment.model';
import { EntityGroup, LedgerProfitRequest, LedgerProfitResponse } from '../models/ledger.model';

@Injectable({ providedIn: 'root' })
export class InvestmentApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiUrl}/investment`;

  getCategories(): Observable<InvestmentCategory[]> {
    return this.http.get<InvestmentCategory[]>(`${this.baseUrl}/categories`);
  }

  getAssetTypes(categoryId?: string): Observable<AssetType[]> {
    const url = categoryId
      ? `${this.baseUrl}/asset-types?category_id=${encodeURIComponent(categoryId)}`
      : `${this.baseUrl}/asset-types`;
    return this.http.get<AssetType[]>(url);
  }

  createAssetType(payload: AssetTypeCreate): Observable<AssetType> {
    return this.http.post<AssetType>(`${this.baseUrl}/asset-types`, payload);
  }

  updateAssetType(assetTypeId: string, payload: AssetTypeUpdate): Observable<AssetType> {
    return this.http.patch<AssetType>(
      `${this.baseUrl}/asset-types/${encodeURIComponent(assetTypeId)}`,
      payload,
    );
  }

  updateCategoryAssetDisplayOrder(
    categoryId: string,
    payload: CategoryAssetDisplayOrderUpdate,
  ): Observable<AssetType[]> {
    return this.http.put<AssetType[]>(
      `${this.baseUrl}/categories/${encodeURIComponent(categoryId)}/asset-types/display-order`,
      payload,
    );
  }

  getOverview(year: number, month: number): Observable<InvestmentOverviewResponse> {
    return this.http.get<InvestmentOverviewResponse>(`${this.baseUrl}/${year}/${month}`);
  }

  getCategoryDetail(year: number, month: number, categoryId: string): Observable<CategoryDetailResponse> {
    return this.http.get<CategoryDetailResponse>(
      `${this.baseUrl}/${year}/${month}/categories/${encodeURIComponent(categoryId)}`,
    );
  }

  upsertCategoryAssets(
    year: number,
    month: number,
    categoryId: string,
    payload: AssetInvestmentsUpsert,
  ): Observable<CategoryDetailResponse> {
    return this.http.post<CategoryDetailResponse>(
      `${this.baseUrl}/${year}/${month}/categories/${encodeURIComponent(categoryId)}/assets`,
      payload,
    );
  }

  getAssetSalesList(): Observable<AssetSalesListResponse> {
    return this.http.get<AssetSalesListResponse>(`${this.baseUrl}/asset-sales`);
  }

  getAssetSaleContext(
    year: number,
    month: number,
    assetTypeId: string,
  ): Observable<AssetSaleContextResponse> {
    return this.http.get<AssetSaleContextResponse>(
      `${this.baseUrl}/${year}/${month}/asset-types/${encodeURIComponent(assetTypeId)}/sale-context`,
    );
  }

  registerAssetSale(
    year: number,
    month: number,
    assetTypeId: string,
    payload: AssetSaleCreate,
  ): Observable<AssetSaleRead> {
    return this.http.post<AssetSaleRead>(
      `${this.baseUrl}/${year}/${month}/asset-types/${encodeURIComponent(assetTypeId)}/sales`,
      payload,
    );
  }

  getInvestmentLedger(): Observable<EntityGroup[]> {
    return this.http.get<EntityGroup[]>(`${this.baseUrl}/ledger`);
  }

  calculateLedgerProfit(payload: LedgerProfitRequest): Observable<LedgerProfitResponse> {
    return this.http.post<LedgerProfitResponse>(`${this.baseUrl}/ledger/profit`, payload);
  }

  getLedgerUnitPrice(
    year: number,
    month: number,
    priceEur: number,
    currency: string,
  ): Observable<{ price: number; currency: string; fx_usd_to_eur: number }> {
    const params = new URLSearchParams({
      price_eur: String(priceEur),
      currency,
    });
    return this.http.get<{ price: number; currency: string; fx_usd_to_eur: number }>(
      `${this.baseUrl}/${year}/${month}/ledger/unit-price?${params.toString()}`,
    );
  }
}
