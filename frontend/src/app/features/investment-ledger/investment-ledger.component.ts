import { CurrencyPipe, DatePipe, DecimalPipe } from '@angular/common';
import { Component, input, signal } from '@angular/core';

import { AssetGroup, AssetTransactionRow, EntityGroup } from '../../core/models/ledger.model';
import { LedgerProfitDialogComponent } from './components/ledger-profit-dialog/ledger-profit-dialog.component';

/** Tolerancia para comparar precios ya redondeados a 2 decimales por el backend. */
const PRICE_EPSILON = 0.005;

function round8(value: number): number {
  return Math.round(value * 1e8) / 1e8;
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

/**
 * Vista de "libro mayor" de inversiones: replica el Excel de seguimiento,
 * agrupado estrictamente por entidad financiera → aportaciones fiat → activos.
 *
 * Componente puramente presentacional: recibe los datos ya agregados por el
 * backend y solo se encarga del renderizado (tablas + formato).
 */
@Component({
  selector: 'app-investment-ledger',
  imports: [CurrencyPipe, DecimalPipe, DatePipe, LedgerProfitDialogComponent],
  templateUrl: './investment-ledger.component.html',
  styleUrl: './investment-ledger.component.scss',
})
export class InvestmentLedgerComponent {
  readonly entities = input.required<EntityGroup[]>();
  readonly year = input.required<number>();
  readonly month = input.required<number>();

  readonly profitDialogOpen = signal(false);
  readonly profitDialogAsset = signal<AssetGroup | null>(null);

  hasFiatDeposits(entity: EntityGroup): boolean {
    return !!entity.fiat_deposits && entity.fiat_deposits.length > 0;
  }

  hasTransactions(asset: AssetGroup): boolean {
    return asset.transactions.length > 0;
  }

  /**
   * Colapsa en una sola fila las operaciones consecutivas con la misma fecha y el
   * mismo precio de compra: suele ser el exchange repartiendo una orden en varios
   * fills. `euros_metidos` y `asset_comprado` se suman; el resto de columnas
   * (medias/acumulados) se quedan con el valor de la última operación del grupo,
   * que ya refleja el acumulado correcto.
   */
  groupedTransactions(asset: AssetGroup): AssetTransactionRow[] {
    const grouped: AssetTransactionRow[] = [];

    for (const tx of asset.transactions) {
      const last = grouped[grouped.length - 1];
      const sameGroup =
        !!last && last.fecha === tx.fecha && Math.abs(last.precio_compra - tx.precio_compra) < PRICE_EPSILON;

      if (sameGroup) {
        last.euros_metidos = round2(last.euros_metidos + tx.euros_metidos);
        last.asset_comprado = round8(last.asset_comprado + tx.asset_comprado);
        last.precio_promedio = tx.precio_promedio;
        last.euros_totales = tx.euros_totales;
        last.asset_acumulado = tx.asset_acumulado;
      } else {
        grouped.push({ ...tx });
      }
    }

    return grouped;
  }

  openProfitDialog(asset: AssetGroup): void {
    this.profitDialogAsset.set(asset);
    this.profitDialogOpen.set(true);
  }

  closeProfitDialog(): void {
    this.profitDialogOpen.set(false);
    this.profitDialogAsset.set(null);
  }
}
