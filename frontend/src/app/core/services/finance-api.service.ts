import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import { Entity } from '../models/entity.model';
import { MonthlyExpensesResponse } from '../models/expense.model';
import {
  EntityBalanceInput,
  ImportPayload,
  HybridBalanceImport,
  MonthlyRecordResponse,
  MonthlyRecordUpsert,
  TimelineResponse,
} from '../models/monthly-record.model';
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

  patchEntityBalances(
    year: number,
    month: number,
    balances: EntityBalanceInput[],
  ): Observable<MonthlyRecordResponse> {
    return this.http.patch<MonthlyRecordResponse>(
      `${this.baseUrl}/records/${year}/${month}/balances`,
      { balances },
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

  getTransactionSyncStatus(): Observable<{ running: boolean }> {
    return this.http.get<{ running: boolean }>(`${this.baseUrl}/sync/transactions/status`);
  }

  triggerTransactionSync(): Observable<{ status: string }> {
    return this.http.post<{ status: string }>(`${this.baseUrl}/sync/transactions`, {});
  }

  getMonthlyExpenses(year: number, month: number): Observable<MonthlyExpensesResponse> {
    return this.http.get<MonthlyExpensesResponse>(`${this.baseUrl}/expenses/${year}/${month}`);
  }

  importExpenses(year: number, month: number, files: File[]): Observable<MonthlyExpensesResponse> {
    const formData = new FormData();
    for (const file of files) {
      formData.append('files', file, file.name);
    }
    return this.http.post<MonthlyExpensesResponse>(
      `${this.baseUrl}/expenses/${year}/${month}/import`,
      formData,
    );
  }

  deleteMonthlyExpenses(year: number, month: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/expenses/${year}/${month}`);
  }
}
