import { Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { Entity } from '../../../../core/models/entity.model';
import { AssetInvestmentDetail, PriceSource } from '../../../../core/models/investment.model';
import { FinanceApiService } from '../../../../core/services/finance-api.service';
import { InvestmentApiService } from '../../../../core/services/investment-api.service';

@Component({
  selector: 'app-asset-edit-dialog',
  imports: [FormsModule],
  templateUrl: './asset-edit-dialog.component.html',
  styleUrl: './asset-edit-dialog.component.scss',
})
export class AssetEditDialogComponent {
  private readonly financeApi = inject(FinanceApiService);
  private readonly investmentApi = inject(InvestmentApiService);

  readonly open = input.required<boolean>();
  readonly categoryId = input.required<string>();
  readonly asset = input.required<AssetInvestmentDetail | null>();

  readonly close = output<void>();
  readonly saved = output<void>();

  readonly allEntities = signal<Entity[]>([]);
  readonly ticker = signal('');
  readonly currency = signal<'EUR' | 'USD'>('EUR');
  readonly entityId = signal<string>('');
  readonly priceSource = signal<PriceSource | ''>('');
  readonly saving = signal(false);
  readonly errorMessage = signal<string | null>(null);

  /** Entidades elegibles + la vinculada al activo aunque no sea INVESTED/HYBRID. */
  readonly entityOptions = computed(() => {
    const currentId = this.entityId();
    const currentName = this.asset()?.entity_name;
    const linkable = this.allEntities().filter(
      (entity) => entity.entity_type === 'INVESTED' || entity.entity_type === 'HYBRID',
    );

    if (!currentId || linkable.some((entity) => entity.id === currentId)) {
      return linkable;
    }

    return [
      ...linkable,
      {
        id: currentId,
        name: currentName ?? currentId,
        entity_type: 'INVESTED' as const,
        is_active: true,
        uses_contribution_ledger: false,
      },
    ];
  });

  constructor() {
    effect(() => {
      if (!this.open()) {
        return;
      }

      const asset = this.asset();
      if (!asset) {
        return;
      }

      this.ticker.set(asset.ticker ?? '');
      this.currency.set(asset.currency === 'USD' ? 'USD' : 'EUR');
      this.entityId.set(asset.entity_id ?? '');
      this.errorMessage.set(null);
      this.refreshAssetCatalog(asset.asset_type_id);
      // El detalle mensual no trae price_source; se completa al refrescar el catálogo abajo.
    });

    effect(() => {
      if (this.open()) {
        this.loadEntities();
      }
    });
  }

  private loadEntities(): void {
    this.financeApi.getActiveEntities().subscribe({
      next: (entities) => this.allEntities.set(entities),
      error: () => this.allEntities.set([]),
    });
  }

  /** Refresca ticker/divisa/entidad desde el catálogo por si el detalle del mes va desactualizado. */
  private refreshAssetCatalog(assetTypeId: string): void {
    this.investmentApi.getAssetTypes(this.categoryId()).subscribe({
      next: (types) => {
        const catalog = types.find((type) => type.id === assetTypeId);
        if (!catalog) {
          return;
        }
        this.ticker.set(catalog.ticker ?? '');
        this.currency.set(catalog.currency === 'USD' ? 'USD' : 'EUR');
        this.entityId.set(catalog.entity_id ?? '');
        this.priceSource.set(catalog.price_source ?? '');
      },
    });
  }

  onTickerChange(value: string): void {
    this.ticker.set(value);
  }

  onPriceSourceChange(value: string): void {
    this.priceSource.set(value === 'kucoin' || value === 'yahoo' ? value : '');
  }

  onCurrencyChange(value: string): void {
    this.currency.set(value === 'USD' ? 'USD' : 'EUR');
  }

  onEntityChange(value: string): void {
    this.entityId.set(value);
  }

  entityTypeLabel(entity: Entity): string {
    if (entity.entity_type === 'HYBRID') {
      return 'Híbrida';
    }
    if (entity.entity_type === 'INVESTED') {
      return 'Inversión';
    }
    return entity.entity_type;
  }

  save(): void {
    const asset = this.asset();
    if (!asset || this.saving()) {
      return;
    }

    this.saving.set(true);
    this.errorMessage.set(null);

    const entityId = this.entityId().trim() || null;
    const ticker = this.ticker().trim() || null;
    const priceSource = this.priceSource() || null;

    this.investmentApi
      .updateAssetType(asset.asset_type_id, {
        ticker,
        currency: this.currency(),
        entity_id: entityId,
        price_source: priceSource,
      })
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.saved.emit();
        },
        error: (err) => {
          this.saving.set(false);
          const httpError = err as { error?: { detail?: string } };
          this.errorMessage.set(httpError?.error?.detail ?? 'No se pudo guardar el activo.');
        },
      });
  }
}
