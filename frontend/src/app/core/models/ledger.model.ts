/**
 * Estructura pensada para replicar el Excel de seguimiento de inversiones,
 * agrupado por entidad financiera (KuCoin, MyInvestor, ...).
 *
 * El backend (FastAPI) es responsable de agregar y devolver ya esta jerarquía;
 * el frontend solo la renderiza.
 */

export interface FiatDeposit {
  fecha: string;
  /** Importe ingresado en EUR. */
  cantidad: number;
  /** Suma acumulada de aportaciones fiat hasta esta fecha (inclusive). */
  total_acumulado: number;
}

export interface AssetTransactionRow {
  fecha: string;
  /** Divisa de asset_types. Los importes de la fila están en esta divisa. */
  currency: string;
  /** Precio medio de compra acumulado hasta esta operación, en `currency`. */
  precio_promedio: number;
  /** Precio de ejecución de esta operación, en `currency`. */
  precio_compra: number;
  /** Importe de esta operación, en `currency`. */
  euros_metidos: number;
  /** Importe acumulado invertido en este activo hasta esta operación, en `currency`. */
  euros_totales: number;
  /** Cantidad de unidades del activo compradas en esta operación. */
  asset_comprado: number;
  /** Cantidad de unidades acumuladas del activo hasta esta operación. */
  asset_acumulado: number;
}

export interface AssetGroup {
  asset_type_id: string;
  /** Ticker del activo en el exchange, p. ej. 'BTC', 'ETH'. */
  exchange_ticker: string;
  /** Divisa nativa del activo (EUR o USD). */
  currency: string;
  total_asset_acumulado: number;
  total_euros_metidos: number;
  last_precio_compra: number;
  transactions: AssetTransactionRow[];
}

export interface LedgerProfitRequest {
  asset_acumulado: number;
  euros_totales: number;
  price: number;
  currency: 'EUR' | 'USD';
  year: number;
  month: number;
}

export interface LedgerProfitResponse {
  /** Beneficio/pérdida en EUR. */
  profit: number;
  profit_percentage: number;
  fx_usd_to_eur: number;
}

export interface EntityGroup {
  entity_name: string;
  /** Histórico de ingresos fiat; ausente/vacío en entidades sin aportaciones registradas (p. ej. MyInvestor). */
  fiat_deposits?: FiatDeposit[];
  assets: AssetGroup[];
}

export type DashboardData = EntityGroup[];
