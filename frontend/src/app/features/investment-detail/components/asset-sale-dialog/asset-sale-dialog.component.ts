import { DecimalPipe } from '@angular/common';
import { Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AssetInvestmentDetail, AssetSaleContextResponse } from '../../../../core/models/investment.model';
import { InvestmentApiService } from '../../../../core/services/investment-api.service';
import { parseDecimalInput } from '../../../../core/utils/parse-decimal';

export type SaleCostMethod = 'pmp' | 'broker';

function round4(value: number): number {
  return Math.round(value * 10_000) / 10_000;
}

function todayIsoDate(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${month}-${day}`;
}

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
  readonly feeInput = signal('');
  readonly saleDateInput = signal(todayIsoDate());
  readonly costMethod = signal<SaleCostMethod>('pmp');
  readonly brokerRemainderInput = signal('');

  readonly parsedUnits = computed(() => parseDecimalInput(this.unitsInput()) ?? null);
  readonly parsedSalePrice = computed(() => parseDecimalInput(this.salePriceInput()) ?? null);
  readonly parsedFee = computed(() => {
    const raw = this.feeInput().trim();
    if (raw === '') {
      return 0;
    }
    const value = parseDecimalInput(raw);
    return value === null || value < 0 ? null : value;
  });

  readonly parsedBrokerRemainder = computed(() => {
    if (this.costMethod() !== 'broker') {
      return null;
    }
    const value = parseDecimalInput(this.brokerRemainderInput());
    return value === null || value < 0 ? null : value;
  });

  readonly imputedCostBasis = computed(() => {
    const ctx = this.context();
    const units = this.parsedUnits();
    if (!ctx || units === null || units <= 0) {
      return null;
    }

    if (this.costMethod() === 'pmp') {
      return round4(units * ctx.avg_buy_price);
    }

    const remainder = this.parsedBrokerRemainder();
    if (remainder === null) {
      return null;
    }
    const positionCost = ctx.position_cost_basis ?? ctx.cost_basis_total;
    const cost = round4(positionCost - remainder);
    if (cost <= 0 || remainder > positionCost) {
      return null;
    }
    return cost;
  });

  readonly preview = computed(() => {
    const ctx = this.context();
    const units = this.parsedUnits();
    const salePrice = this.parsedSalePrice();
    const fee = this.parsedFee();
    const costBasis = this.imputedCostBasis();
    if (
      !ctx ||
      units === null ||
      units <= 0 ||
      salePrice === null ||
      salePrice < 0 ||
      fee === null ||
      costBasis === null
    ) {
      return null;
    }
    if (units > ctx.available_units) {
      return null;
    }

    const netLiquidity = round4(units * salePrice - fee);
    const netProfit = round4(netLiquidity - costBasis);
    const avgBuyPrice = round4(costBasis / units);
    const profitPct = costBasis > 0 ? round4((netProfit / costBasis) * 100) : 0;
    const sharePct =
      ctx.position_units > 0 ? round4((units / ctx.position_units) * 100) : 0;

    return {
      netLiquidity,
      costBasis,
      netProfit,
      avgBuyPrice,
      profitPct,
      sharePct,
      fee,
    };
  });

  constructor() {
    effect(() => {
      if (!this.open()) {
        this.context.set(null);
        this.unitsInput.set('');
        this.salePriceInput.set('');
        this.feeInput.set('');
        this.brokerRemainderInput.set('');
        this.costMethod.set('pmp');
        this.saleDateInput.set(todayIsoDate());
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

  onFeeChange(value: string): void {
    this.feeInput.set(value);
  }

  onBrokerRemainderChange(value: string): void {
    this.brokerRemainderInput.set(value);
  }

  onSaleDateChange(value: string): void {
    this.saleDateInput.set(value);
  }

  setCostMethod(method: SaleCostMethod): void {
    this.costMethod.set(method);
    if (method === 'pmp') {
      this.brokerRemainderInput.set('');
    }
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
    const units = this.parsedUnits();
    const salePrice = this.parsedSalePrice();
    const fee = this.parsedFee();
    const costBasis = this.imputedCostBasis();
    const preview = this.preview();
    if (
      !asset ||
      units === null ||
      units <= 0 ||
      salePrice === null ||
      fee === null ||
      costBasis === null ||
      !preview ||
      this.saving()
    ) {
      return;
    }

    const ctx = this.context();
    if (ctx && units > ctx.available_units) {
      this.errorMessage.set(`Máximo ${ctx.available_units} títulos disponibles.`);
      return;
    }

    this.saving.set(true);
    this.errorMessage.set(null);

    const payload = {
      units,
      sale_price: salePrice,
      fee,
      sale_date: this.saleDateInput(),
      cost_basis: this.costMethod() === 'broker' ? costBasis : undefined,
    };

    this.investmentApi
      .registerAssetSale(this.year(), this.month(), asset.asset_type_id, payload)
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
