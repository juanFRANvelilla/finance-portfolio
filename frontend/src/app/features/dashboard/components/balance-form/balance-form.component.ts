import { Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { EntityContributionsResponse } from '../../../../core/models/contribution.model';
import { Entity } from '../../../../core/models/entity.model';
import { EntityBalanceInput, HybridBalanceImport, MonthlyRecord } from '../../../../core/models/monthly-record.model';
import { FinanceApiService } from '../../../../core/services/finance-api.service';
import { InvestmentApiService } from '../../../../core/services/investment-api.service';
import { EurCurrencyPipe } from '../../../../core/pipes/eur-currency.pipe';
import { parseDecimalInput } from '../../../../core/utils/parse-decimal';
import { ContributionsDialogComponent } from '../contributions-dialog/contributions-dialog.component';

export interface BalanceFormSubmission {
  balances: EntityBalanceInput[];
  hybridBalances: HybridBalanceImport[];
}

export interface HybridFormSubmission {
  hybridBalances: HybridBalanceImport[];
}

interface HybridLedgerState {
  previousStaticTotal: number;
  contributionsTotal: number;
  projectedTotal: number;
  cumulativeInvested: number;
}

@Component({
  selector: 'app-balance-form',
  imports: [FormsModule, EurCurrencyPipe, ContributionsDialogComponent],
  templateUrl: './balance-form.component.html',
  styleUrl: './balance-form.component.scss',
})
export class BalanceFormComponent {
  private readonly api = inject(FinanceApiService);
  private readonly investmentApi = inject(InvestmentApiService);

  readonly entities = input.required<Entity[]>();
  readonly year = input.required<number>();
  readonly month = input.required<number>();
  readonly saving = input<boolean>(false);
  readonly updating = input<boolean>(false);
  readonly editMode = input<boolean>(false);
  readonly initialRecord = input<MonthlyRecord | null>(null);
  readonly entityBalancePreviews = input<Record<string, number>>({});
  readonly save = output<BalanceFormSubmission>();
  readonly updateHybrids = output<HybridFormSubmission>();
  readonly cancelEdit = output<void>();

  readonly simpleEntities = computed(() =>
    this.entities().filter((e) => e.entity_type === 'LIQUID' || e.entity_type === 'INVESTED'),
  );

  readonly hybridEntities = computed(() => this.entities().filter((e) => e.entity_type === 'HYBRID'));

  /** Híbridas con libro de aportaciones primero (ocupan más ancho en la fila). */
  readonly hybridEntitiesOrdered = computed(() =>
    [...this.hybridEntities()].sort((a, b) => {
      if (a.uses_contribution_ledger === b.uses_contribution_ledger) {
        return 0;
      }
      return a.uses_contribution_ledger ? -1 : 1;
    }),
  );

  usesContributionLedger(entityId: string): boolean {
    return this.entities().find((entity) => entity.id === entityId)?.uses_contribution_ledger ?? false;
  }

  hasLinkedAssetTypes(entityId: string): boolean {
    return this.hybridEntitiesWithLinkedAssets().has(entityId);
  }

  isLoadingLinkedInvested(entityId: string): boolean {
    return this.loadingLinkedInvested()[entityId] ?? false;
  }

  private loadHybridEntitiesWithLinkedAssets(): void {
    this.investmentApi.getAssetTypes().subscribe({
      next: (assets) => {
        const linked = new Set<string>();
        for (const asset of assets) {
          if (asset.entity_id) {
            linked.add(asset.entity_id);
          }
        }
        this.hybridEntitiesWithLinkedAssets.set(linked);
      },
      error: () => this.hybridEntitiesWithLinkedAssets.set(new Set()),
    });
  }

  readonly values = signal<Record<string, number | null>>({});
  readonly hybridLiquid = signal<Record<string, number | null>>({});
  readonly hybridInvested = signal<Record<string, number | null>>({});
  readonly hybridInvestedOverridden = signal<Record<string, boolean>>({});
  readonly hybridLedger = signal<Record<string, HybridLedgerState>>({});
  readonly hybridEntitiesWithLinkedAssets = signal<Set<string>>(new Set());
  readonly loadingLinkedInvested = signal<Record<string, boolean>>({});

  readonly contributionsDialogOpen = signal(false);
  readonly contributionsEntityId = signal<string | null>(null);
  readonly contributionsEntityName = signal('');

  readonly activeContributionsEntityId = computed(() => this.contributionsEntityId() ?? '');
  readonly activeContributionsLiquid = computed(() => {
    const id = this.contributionsEntityId();
    if (!id) return 0;
    return this.hybridLiquid()[id] ?? 0;
  });

  /** En modo edición, true solo si algún campo difiere del registro cargado. */
  readonly hasPendingChanges = computed(() => {
    if (!this.editMode()) {
      return true;
    }

    const record = this.initialRecord();
    if (!record) {
      return false;
    }

    for (const entity of this.simpleEntities()) {
      const current = this.values()[entity.id] ?? 0;
      const previous = record.balances.find((row) => row.entity_id === entity.id);
      const previousAmount = previous?.balance_amount ?? 0;
      if (current !== previousAmount) {
        return true;
      }
    }

    for (const entity of this.hybridEntities()) {
      const currentLiquid = this.hybridLiquid()[entity.id] ?? 0;
      const currentInvested = this.resolveHybridInvested(entity.id);
      const previous = record.hybrid_accounts.find((row) => row.entity_id === entity.id);
      if (!previous) {
        if (currentLiquid !== 0 || currentInvested !== 0) {
          return true;
        }
        continue;
      }
      if (currentLiquid !== previous.liquid_amount || currentInvested !== previous.cumulative_invested) {
        return true;
      }
    }

    return false;
  });

  readonly canSubmit = computed(() => {
    if (this.saving()) {
      return false;
    }
    if (this.simpleEntities().length === 0 && this.hybridEntities().length === 0) {
      return false;
    }
    if (this.editMode()) {
      return this.hasPendingChanges();
    }
    return true;
  });

  constructor() {
    effect(() => {
      this.year();
      this.month();
      this.values.set({});
      this.hybridLiquid.set({});
      this.hybridInvested.set({});
      this.hybridInvestedOverridden.set({});
      this.loadHybridEntitiesWithLinkedAssets();
    });

    effect(() => {
      const previews = this.entityBalancePreviews();
      this.values.update((current) => {
        if (Object.keys(current).length > 0) {
          const next = { ...current };
          for (const entity of this.simpleEntities()) {
            if (!(entity.id in next)) {
              next[entity.id] = previews[entity.id] ?? 0;
            }
          }
          return next;
        }

        const next: Record<string, number | null> = {};
        for (const entity of this.simpleEntities()) {
          next[entity.id] = previews[entity.id] ?? 0;
        }
        return next;
      });
    });

    effect(() => {
      const record = this.initialRecord();
      if (!record) {
        return;
      }

      const liquid: Record<string, number | null> = {};
      const invested: Record<string, number | null> = {};
      const overridden: Record<string, boolean> = {};
      for (const hybrid of record.hybrid_accounts) {
        liquid[hybrid.entity_id] = hybrid.liquid_amount;
        invested[hybrid.entity_id] = hybrid.cumulative_invested;
        overridden[hybrid.entity_id] = true;
      }
      this.hybridLiquid.set(liquid);
      this.hybridInvested.set(invested);
      this.hybridInvestedOverridden.set(overridden);

      this.values.update((current) => {
        const next = { ...current };
        for (const balance of record.balances) {
          next[balance.entity_id] = balance.balance_amount;
        }
        return next;
      });
    });

    effect(() => {
      const hybrids = this.hybridEntities();
      this.year();
      this.month();
      for (const entity of hybrids) {
        if (this.usesContributionLedger(entity.id)) {
          this.refreshHybridLedger(entity.id);
        }
      }
    });
  }

  displayAmount(value: number | null | undefined): string {
    if (value === null || value === undefined) {
      return '';
    }
    return String(value).replace('.', ',');
  }

  onValueChange(entityId: string, value: string): void {
    const parsed = parseDecimalInput(value);
    this.values.update((current) => ({ ...current, [entityId]: parsed }));
  }

  onHybridLiquidChange(entityId: string, value: string): void {
    const parsed = parseDecimalInput(value);
    this.hybridLiquid.update((current) => ({ ...current, [entityId]: parsed }));
    if (this.usesContributionLedger(entityId)) {
      this.refreshHybridLedger(entityId);
    }
  }

  onHybridInvestedChange(entityId: string, value: string): void {
    const parsed = parseDecimalInput(value);
    this.hybridInvested.update((current) => ({ ...current, [entityId]: parsed }));
    this.hybridInvestedOverridden.update((current) => ({ ...current, [entityId]: true }));
  }

  applyLinkedAssetsInvested(entityId: string): void {
    this.loadingLinkedInvested.update((current) => ({ ...current, [entityId]: true }));
    this.investmentApi.getLinkedInvestedTotal(this.year(), this.month(), entityId).subscribe({
      next: (response) => {
        this.hybridInvested.update((current) => ({ ...current, [entityId]: response.total_eur }));
        this.hybridInvestedOverridden.update((current) => ({ ...current, [entityId]: true }));
        this.loadingLinkedInvested.update((current) => ({ ...current, [entityId]: false }));
      },
      error: () => {
        this.loadingLinkedInvested.update((current) => ({ ...current, [entityId]: false }));
      },
    });
  }

  hybridInvestedPreview(entityId: string): number {
    return this.hybridLedger()[entityId]?.cumulativeInvested ?? 0;
  }

  openContributionsDialog(entity: Entity): void {
    this.contributionsEntityId.set(entity.id);
    this.contributionsEntityName.set(entity.name);
    this.contributionsDialogOpen.set(true);
  }

  closeContributionsDialog(): void {
    this.contributionsDialogOpen.set(false);
    this.contributionsEntityId.set(null);
  }

  onContributionsChanged(entityId: string, summary: EntityContributionsResponse): void {
    this.hybridLedger.update((current) => ({
      ...current,
      [entityId]: {
        previousStaticTotal: summary.previous_static_total,
        contributionsTotal: summary.contributions_total,
        projectedTotal: summary.projected_total,
        cumulativeInvested: summary.cumulative_invested_preview,
      },
    }));

    if (!this.hybridInvestedOverridden()[entityId]) {
      this.hybridInvested.update((current) => ({
        ...current,
        [entityId]: summary.cumulative_invested_preview,
      }));
    }
  }

  private refreshHybridLedger(entityId: string): void {
    if (!this.usesContributionLedger(entityId)) {
      return;
    }

    const liquid = this.hybridLiquid()[entityId] ?? 0;
    this.api.getEntityContributions(this.year(), this.month(), entityId, liquid).subscribe({
      next: (summary) => this.onContributionsChanged(entityId, summary),
      error: () => {
        this.hybridLedger.update((current) => ({
          ...current,
          [entityId]: {
            previousStaticTotal: 0,
            contributionsTotal: 0,
            projectedTotal: 0,
            cumulativeInvested: 0,
          },
        }));
      },
    });
  }

  private resolveHybridInvested(entityId: string): number {
    const manual = this.hybridInvested()[entityId];
    if (manual !== null && manual !== undefined) {
      return manual;
    }
    if (this.usesContributionLedger(entityId)) {
      return this.hybridInvestedPreview(entityId);
    }
    return 0;
  }

  private buildHybridBalances(): HybridBalanceImport[] {
    return this.hybridEntities().map((entity) => ({
      entity_id: entity.id,
      liquid_amount: this.hybridLiquid()[entity.id] ?? 0,
      invested_amount: this.resolveHybridInvested(entity.id),
    }));
  }

  onUpdateHybridsClick(): void {
    this.updateHybrids.emit({ hybridBalances: this.buildHybridBalances() });
  }

  onSubmit(): void {
    if (this.editMode() && !this.hasPendingChanges()) {
      return;
    }

    const hybridBalances = this.buildHybridBalances();

    const balances: EntityBalanceInput[] = this.simpleEntities().map((entity) => ({
      entity_id: entity.id,
      balance_amount: this.values()[entity.id] ?? 0,
    }));

    this.save.emit({ balances, hybridBalances });
  }
}
