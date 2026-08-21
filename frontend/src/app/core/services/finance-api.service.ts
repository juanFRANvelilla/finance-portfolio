import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import { Entity } from '../models/entity.model';
import {
  ImportPayload,
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
}
