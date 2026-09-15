import { DecimalPipe } from '@angular/common';
import { Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AssetInvestmentDetail, AssetSaleContextResponse } from '../../../../core/models/investment.model';
import { InvestmentApiService } from '../../../../core/services/investment-api.service';
import { parseDecimalInput } from '../../../../core/utils/parse-decimal';
import { round2 } from '../../../../core/utils/live-investment-summary';

@Component({
  selector: 'app-asset-sale-dialog',
  imports: [FormsModule, DecimalPipe],
  templateUrl: './asset-sale-dialog.component.html',
  styleUrl: '../asset-edit-dialog/asset-edit-dialog.component.scss',
})
export class AssetSaleDialogComponent {
  private readonly investmentApi = inject(InvestmentApiService);

  readonly open = input.required<boolean>();
  readonly year = input.required<number>();
  readonly month = input.required<number>();
  readonly asset = input.required<AssetInvestmentDetail | null>();

  readonly close = output<void>();
  readonly saved = output<void>();

  readonly loading = signal(false);
  readonly saving = signal(false);
  readonly errorMessage = signal<string | null>(null);
  readonly context = signal<AssetSaleContextResponse | null>(null);

  readonly unitsInput = signal('');
  readonly salePriceInput = signal('');

  readonly parsedUnits = computed(() => parseDecimalInput(this.unitsInput()) ?? null);
  readonly parsedSalePrice = computed(() => parseDecimalInput(this.salePriceInput()) ?? null);

  readonly preview = computed(() => {
    const ctx = this.context();
    const units = this.parsedUnits();
    const salePrice = this.parsedSalePrice();
    if (!ctx || units === null || units <= 0 || salePrice === null || salePrice < 0) {
      return null;
    }
    if (units > ctx.available_units) {
      return null;
    }
    const profit = round2((salePrice - ctx.avg_buy_price) * units);
    const profitPct =
      ctx.avg_buy_price > 0
        ? round2(((salePrice - ctx.avg_buy_price) / ctx.avg_buy_price) * 100)
        : 0;
    const sharePct =
      ctx.position_units > 0 ? round2((units / ctx.position_units) * 100) : 0;
    return { profit, profitPct, sharePct, proceeds: round2(salePrice * units) };
  });

  constructor() {
    effect(() => {
      if (!this.open()) {
        this.context.set(null);
        this.unitsInput.set('');
        this.salePriceInput.set('');
        this.errorMessage.set(null);
        return;
      }
      const asset = this.asset();
      if (!asset) {
        return;
      }
      this.loadContext(asset.asset_type_id);
    });
  }

  private loadContext(assetTypeId: string): void {
    this.loading.set(true);
    this.errorMessage.set(null);
    this.investmentApi.getAssetSaleContext(this.year(), this.month(), assetTypeId).subscribe({
      next: (ctx) => {
        this.context.set(ctx);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        const httpError = err as { error?: { detail?: string } };
        this.errorMessage.set(httpError?.error?.detail ?? 'No se pudo cargar la posición del activo.');
      },
    });
  }

  onUnitsChange(value: string): void {
    this.unitsInput.set(value);
  }

  onSalePriceChange(value: string): void {
    this.salePriceInput.set(value);
  }

  sellMaxUnits(): void {
    const ctx = this.context();
    if (ctx) {
      this.unitsInput.set(String(ctx.available_units));
    }
  }

  profitClass(profit: number): string {
    if (profit === 0) {
      return 'text-slate-300';
    }
    return profit > 0 ? 'text-emerald-400' : 'text-rose-400';
  }

  confirmSale(): void {
    const asset = this.asset();
    const ctx = this.context();
    const units = this.parsedUnits();
    const salePrice = this.parsedSalePrice();
    if (!asset || !ctx || units === null || units <= 0 || salePrice === null || this.saving()) {
      return;
    }
    if (units > ctx.available_units) {
      this.errorMessage.set(`Máximo ${ctx.available_units} títulos disponibles.`);
      return;
    }

    this.saving.set(true);
    this.errorMessage.set(null);
    this.investmentApi
      .registerAssetSale(this.year(), this.month(), asset.asset_type_id, {
        units,
        sale_price: salePrice,
      })
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.saved.emit();
        },
        error: (err) => {
          this.saving.set(false);
          const httpError = err as { error?: { detail?: string } };
          this.errorMessage.set(httpError?.error?.detail ?? 'No se pudo registrar la venta.');
        },
      });
  }
}
