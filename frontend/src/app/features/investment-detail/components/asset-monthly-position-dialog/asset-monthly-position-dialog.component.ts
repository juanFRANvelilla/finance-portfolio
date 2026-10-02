import { CurrencyPipe, DecimalPipe } from '@angular/common';
import { Component, effect, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  AssetInvestmentDetail,
  CategoryDetailResponse,
} from '../../../../core/models/investment.model';
import { InvestmentApiService } from '../../../../core/services/investment-api.service';
import {
  formatAmountForInput,
  formatUnitsForInput,
  parseDecimalInput,
} from '../../../../core/utils/parse-decimal';

/** Métricas en vivo pasadas desde el padre (precio, valor, P/L). */
export interface AssetMonthlyLiveMetrics {
  price: number;
  currency: string;
  showEurToggle: boolean;
  marketValue: number | null;
  profit: number | null;
  profitPct: number | null;
}

@Component({
  selector: 'app-asset-monthly-position-dialog',
  imports: [FormsModule, CurrencyPipe, DecimalPipe],
  templateUrl: './asset-monthly-position-dialog.component.html',
  styleUrl: '../asset-edit-dialog/asset-edit-dialog.component.scss',
})
export class AssetMonthlyPositionDialogComponent {
  private readonly investmentApi = inject(InvestmentApiService);

  readonly open = input.required<boolean>();
  readonly categoryId = input.required<string>();
  readonly year = input.required<number>();
  readonly month = input.required<number>();
  readonly asset = input.required<AssetInvestmentDetail | null>();
  readonly liveMetrics = input<AssetMonthlyLiveMetrics | null>(null);
  readonly livePriceUpdatedAt = input<string | null>(null);
  readonly livePriceEurMode = input(false);

  readonly close = output<void>();
  readonly saved = output<CategoryDetailResponse>();
  readonly toggleEurMode = output<void>();
  readonly draftChange = output<{ amount: string; units: string }>();

  readonly amount = signal('');
  readonly units = signal('');
  readonly saving = signal(false);
  readonly errorMessage = signal<string | null>(null);

  /** Evita que un refresh del `asset` input borre lo que el usuario está escribiendo. */
  private seededDialogKey: string | null = null;

  constructor() {
    effect(() => {
      if (!this.open()) {
        this.seededDialogKey = null;
        return;
      }
      const asset = this.asset();
      if (!asset) {
        return;
      }
      const key = `${asset.asset_type_id}:${this.year()}:${this.month()}`;
      if (this.seededDialogKey === key) {
        return;
      }
      this.seededDialogKey = key;
      this.amount.set(formatAmountForInput(asset.amount));
      this.units.set(formatUnitsForInput(asset.units));
      this.errorMessage.set(null);
      this.emitDraft();
    });
  }

  displayCurrencyCode(currency: string): string {
    return currency === 'USDT' ? 'USD' : currency;
  }

  assetLabel(): string {
    const asset = this.asset();
    if (!asset) {
      return '';
    }
    const ticker = asset.ticker?.trim();
    const code = this.displayCurrencyCode(asset.currency);
    if (ticker) {
      return `${ticker} (${code})`;
    }
    return `${asset.name} (${code})`;
  }

  liveCurrencyToggleLabel(): string {
    return this.livePriceEurMode() ? '€' : '$';
  }

  liveCurrencyToggleTitle(): string {
    return this.livePriceEurMode()
      ? 'Mostrando en euros. Pulsa para ver en dólares'
      : 'Mostrando en dólares. Pulsa para ver en euros';
  }

  liveProfitClass(profit: number | null): string {
    if (profit === null || profit === 0) {
      return 'live-price-profit live-price-profit--neutral';
    }
    return profit > 0
      ? 'live-price-profit live-price-profit--gain'
      : 'live-price-profit live-price-profit--loss';
  }

  onAmountChange(value: string): void {
    this.amount.set(value);
    this.emitDraft();
  }

  onUnitsChange(value: string): void {
    this.units.set(value);
    this.emitDraft();
  }

  private emitDraft(): void {
    this.draftChange.emit({ amount: this.amount(), units: this.units() });
  }

  save(): void {
    const asset = this.asset();
    if (!asset || this.saving()) {
      return;
    }

    this.errorMessage.set(null);

    const amount = parseDecimalInput(this.amount());
    if (amount === null) {
      this.errorMessage.set('Importe inválido. Usa coma o punto decimal (p. ej. 15000,50).');
      return;
    }
    const unitsRaw = this.units().trim();
    const units = unitsRaw === '' ? null : parseDecimalInput(unitsRaw);
    if (unitsRaw !== '' && units === null) {
      this.errorMessage.set('Títulos inválidos.');
      return;
    }

    this.saving.set(true);

    this.investmentApi
      .upsertCategoryAssets(this.year(), this.month(), this.categoryId(), {
        assets: [
          {
            asset_type_id: asset.asset_type_id,
            amount,
            units,
          },
        ],
      })
      .subscribe({
        next: (detail) => {
          this.saving.set(false);
          this.saved.emit(detail);
        },
        error: (err) => {
          this.saving.set(false);
          const httpError = err as { error?: { detail?: string } };
          this.errorMessage.set(httpError?.error?.detail ?? 'No se pudo guardar la posición del mes.');
        },
      });
  }
}
