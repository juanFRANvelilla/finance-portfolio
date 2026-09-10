import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import { MarketPriceResponse } from '../models/market-price.model';

@Injectable({ providedIn: 'root' })
export class MarketPriceApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiUrl}/v1`;

  getMarketPrices(refresh = false): Observable<MarketPriceResponse[]> {
    const url = refresh
      ? `${this.baseUrl}/market-prices?refresh=true`
      : `${this.baseUrl}/market-prices`;
    return this.http.get<MarketPriceResponse[]>(url);
  }
}
