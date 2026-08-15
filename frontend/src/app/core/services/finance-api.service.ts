import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import { Entity } from '../models/entity.model';
import {
  ImportJsonResponse,
  MonthlyRecordResponse,
  MonthlyRecordUpsert,
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

  importHistoricalJson(months: unknown[]): Observable<ImportJsonResponse> {
    return this.http.post<ImportJsonResponse>(`${this.baseUrl}/records/import-json`, { months });
  }
}
