import { CurrencyPipe, DecimalPipe } from '@angular/common';
import { Component, effect, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AssetGroup } from '../../../../core/models/ledger.model';
import { InvestmentApiService } from '../../../../core/services/investment-api.service';
import { parseDecimalInput } from '../../../../core/utils/parse-decimal';

@Component({
  selector: 'app-ledger-profit-dialog',
  imports: [FormsModule, CurrencyPipe, DecimalPipe],
  templateUrl: './ledger-profit-dialog.component.html',
  styleUrl: './ledger-profit-dialog.component.scss',
})
export class LedgerProfitDialogComponent {
  private readonly api = inject(InvestmentApiService);

  readonly open = input.required<boolean>();
  readonly asset = input.required<AssetGroup | null>();
  readonly year = input.required<number>();
  readonly month = input.required<number>();

  readonly close = output<void>();

  readonly priceInput = signal('');
  readonly currency = signal<'EUR' | 'USD'>('EUR');
  readonly loading = signal(false);
  readonly errorMessage = signal<string | null>(null);
  readonly profit = signal<number | null>(null);
  readonly profitPercentage = signal<number | null>(null);

  /** Evita reiniciar precio/divisa si el effect se re-ejecuta mientras el popup sigue abierto. */
  private bootstrappedAssetId: string | null = null;

  constructor() {
    effect(() => {
      if (!this.open()) {
        this.bootstrappedAssetId = null;
        return;
      }

      const asset = this.asset();
      if (!asset) {
        return;
      }

      if (this.bootstrappedAssetId === asset.asset_type_id) {
        return;
      }

      this.bootstrappedAssetId = asset.asset_type_id;
      this.bootstrapDefaults(asset);
    });
  }

  private bootstrapDefaults(asset: AssetGroup): void {
    this.errorMessage.set(null);
    this.profit.set(null);
    this.profitPercentage.set(null);
    this.currency.set(asset.currency === 'USD' ? 'USD' : 'EUR');

    this.api
      .getLedgerUnitPrice(this.year(), this.month(), asset.last_precio_compra, this.currency())
      .subscribe({
        next: (response) => {
          this.priceInput.set(this.formatPriceInput(response.price));
          this.recalculate();
        },
        error: () => {
          this.priceInput.set(this.formatPriceInput(asset.last_precio_compra));
          this.recalculate();
        },
      });
  }

  onPriceChange(value: string): void {
    this.priceInput.set(value);
    this.recalculate();
  }

  onCurrencyChange(value: string): void {
    const next = value === 'USD' ? 'USD' : 'EUR';
    this.currency.set(next);
    // Mantiene el precio unitario tal cual; solo cambia cómo se interpreta la divisa.
    this.recalculate();
  }

  recalculate(): void {
    const asset = this.asset();
    if (!asset) {
      return;
    }

    const price = parseDecimalInput(this.priceInput());
    if (price === null || price <= 0) {
      this.profit.set(null);
      this.profitPercentage.set(null);
      this.errorMessage.set(null);
      return;
    }

    this.loading.set(true);
    this.errorMessage.set(null);

    this.api
      .calculateLedgerProfit({
        asset_acumulado: asset.total_asset_acumulado,
        euros_totales: asset.total_euros_metidos,
        price,
        currency: this.currency(),
        year: this.year(),
        month: this.month(),
      })
      .subscribe({
        next: (response) => {
          this.profit.set(response.profit);
          this.profitPercentage.set(response.profit_percentage);
          this.loading.set(false);
        },
        error: () => {
          this.errorMessage.set('No se pudo calcular el beneficio.');
          this.profit.set(null);
          this.profitPercentage.set(null);
          this.loading.set(false);
        },
      });
  }

  profitClass(): string {
    const value = this.profit();
    if (value === null) {
      return 'text-slate-300';
    }
    return value >= 0 ? 'text-emerald-400' : 'text-rose-400';
  }

  private formatPriceInput(value: number): string {
    return String(value).replace('.', ',');
  }
}
