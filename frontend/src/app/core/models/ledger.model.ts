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
  /** Precio medio de compra acumulado hasta esta operación (EUR/unidad). */
  precio_promedio: number;
  /** Precio de ejecución de esta operación concreta (EUR/unidad). */
  precio_compra: number;
  /** Importe en EUR destinado a esta operación. */
  euros_metidos: number;
  /** Importe en EUR acumulado invertido en este activo hasta esta operación. */
  euros_totales: number;
  /** Cantidad de unidades del activo compradas en esta operación. */
  asset_comprado: number;
  /** Cantidad de unidades acumuladas del activo hasta esta operación. */
  asset_acumulado: number;
  /**
   * Plusvalía/minusvalía en EUR en el momento de esta fila (valor actual - coste).
   * `null` cuando no hay una fuente de precio de mercado en vivo para valorarlo.
   */
  beneficios: number | null;
}

export interface AssetGroup {
  /** Ticker del activo en el exchange, p. ej. 'BTC', 'ETH'. */
  exchange_ticker: string;
  transactions: AssetTransactionRow[];
}

export interface EntityGroup {
  entity_name: string;
  /** Histórico de ingresos fiat; ausente/vacío en entidades sin aportaciones registradas (p. ej. MyInvestor). */
  fiat_deposits?: FiatDeposit[];
  assets: AssetGroup[];
}

export type DashboardData = EntityGroup[];
