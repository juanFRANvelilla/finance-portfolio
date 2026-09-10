/** Precio de mercado en vivo de un activo, resuelto por el backend (KuCoin o Yahoo Finance). */
export interface MarketPriceResponse {
  asset_type_id: string;
  ticker: string;
  price: number;
  /** Divisa devuelta por el proveedor de origen (p.ej. 'EUR', 'USD', 'USDT'). */
  currency: string;
  /** ISO 8601 UTC, p.ej. '2026-09-10T18:30:00Z'. */
  updated_at: string;
}
