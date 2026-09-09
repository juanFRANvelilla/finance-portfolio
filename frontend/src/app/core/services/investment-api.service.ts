import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  AssetInvestmentsUpsert,
  AssetType,
  AssetTypeCreate,
  AssetTypeUpdate,
  CategoryDetailResponse,
  CategoryInvestmentsUpsert,
  InvestmentCategory,
  InvestmentOverviewResponse,
  LinkedInvestedTotalResponse,
  AssetTransactionPreviewResponse,
} from '../models/investment.model';
import { EntityGroup } from '../models/ledger.model';

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

  getOverview(year: number, month: number): Observable<InvestmentOverviewResponse> {
    return this.http.get<InvestmentOverviewResponse>(`${this.baseUrl}/${year}/${month}`);
  }

  upsertCategories(
    year: number,
    month: number,
    payload: CategoryInvestmentsUpsert,
  ): Observable<InvestmentOverviewResponse> {
    return this.http.post<InvestmentOverviewResponse>(`${this.baseUrl}/${year}/${month}/categories`, payload);
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

  getLinkedInvestedTotal(
    year: number,
    month: number,
    entityId: string,
  ): Observable<LinkedInvestedTotalResponse> {
    return this.http.get<LinkedInvestedTotalResponse>(
      `${this.baseUrl}/${year}/${month}/entities/${encodeURIComponent(entityId)}/linked-invested-total`,
    );
  }

  getAssetTransactionPreview(
    year: number,
    month: number,
    assetTypeId: string,
  ): Observable<AssetTransactionPreviewResponse> {
    return this.http.get<AssetTransactionPreviewResponse>(
      `${this.baseUrl}/${year}/${month}/asset-types/${encodeURIComponent(assetTypeId)}/transaction-preview`,
    );
  }

  getInvestmentLedger(): Observable<EntityGroup[]> {
    return this.http.get<EntityGroup[]>(`${this.baseUrl}/ledger`);
  }
}
