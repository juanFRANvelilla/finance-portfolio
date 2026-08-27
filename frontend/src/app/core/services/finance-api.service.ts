import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import { Entity } from '../models/entity.model';
import {
  ImportPayload,
  HybridBalanceImport,
  MonthlyRecord,
  MonthlyRecordResponse,
  MonthlyRecordUpsert,
  TimelineResponse,
} from '../models/monthly-record.model';
import {
  Contribution,
  ContributionCreate,
  EntityContributionsResponse,
} from '../models/contribution.model';

@Injectable({ providedIn: 'root' })
export class FinanceApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = environment.apiUrl;

  getActiveEntities(): Observable<Entity[]> {
    return this.http.get<Entity[]>(`${this.baseUrl}/entities`);
  }

  getMonthlyRecord(year: number, month: number): Observable<MonthlyRecordResponse> {
    return this.http.get<MonthlyRecordResponse>(`${this.baseUrl}/records/${year}/${month}`);
  }

  getTimeline(): Observable<TimelineResponse> {
    return this.http.get<TimelineResponse>(`${this.baseUrl}/records/timeline`);
  }

  upsertMonthlyRecord(
    year: number,
    month: number,
    payload: MonthlyRecordUpsert,
  ): Observable<MonthlyRecordResponse> {
    return this.http.post<MonthlyRecordResponse>(
      `${this.baseUrl}/records/${year}/${month}`,
      payload,
    );
  }

  patchHybridBalances(
    year: number,
    month: number,
    hybridBalances: HybridBalanceImport[],
  ): Observable<MonthlyRecordResponse> {
    return this.http.patch<MonthlyRecordResponse>(
      `${this.baseUrl}/records/${year}/${month}/hybrids`,
      { hybrid_balances: hybridBalances },
    );
  }

  deleteMonthlyRecord(year: number, month: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/records/${year}/${month}`);
  }

  importMonthlyRecord(
    year: number,
    month: number,
    payload: ImportPayload,
  ): Observable<MonthlyRecordResponse> {
    return this.http.post<MonthlyRecordResponse>(
      `${this.baseUrl}/records/${year}/${month}/import`,
      payload,
    );
  }

  getEntityContributions(
    year: number,
    month: number,
    entityId: string,
    liquidAmount = 0,
  ): Observable<EntityContributionsResponse> {
    return this.http.get<EntityContributionsResponse>(
      `${this.baseUrl}/contributions/${year}/${month}/${encodeURIComponent(entityId)}`,
      { params: { liquid_amount: liquidAmount } },
    );
  }

  createEntityContribution(
    year: number,
    month: number,
    entityId: string,
    payload: ContributionCreate,
  ): Observable<Contribution> {
    return this.http.post<Contribution>(
      `${this.baseUrl}/contributions/${year}/${month}/${encodeURIComponent(entityId)}`,
      payload,
    );
  }

  deleteEntityContribution(contributionId: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/contributions/${contributionId}`);
  }
}
