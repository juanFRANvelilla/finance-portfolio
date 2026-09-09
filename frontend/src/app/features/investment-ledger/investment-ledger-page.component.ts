import { Component, inject, OnInit, signal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';

import { InvestmentApiService } from '../../core/services/investment-api.service';
import { PeriodStorageService } from '../../core/services/period-storage.service';
import { EntityGroup } from '../../core/models/ledger.model';
import { InvestmentLedgerComponent } from './investment-ledger.component';

/**
 * Página real de "Gestionar transacciones": carga el histórico completo de
 * fiat_deposits + asset_transactions (agrupado por entidad) desde el backend.
 */
@Component({
  selector: 'app-investment-ledger-page',
  imports: [InvestmentLedgerComponent],
  templateUrl: './investment-ledger-page.component.html',
})
export class InvestmentLedgerPageComponent implements OnInit {
  private readonly api = inject(InvestmentApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly periodStorage = inject(PeriodStorageService);

  private readonly storedPeriod = this.periodStorage.read();
  readonly year = signal<number>(this.storedPeriod.year);
  readonly month = signal<number>(this.storedPeriod.month);

  readonly loading = signal<boolean>(false);
  readonly errorMessage = signal<string | null>(null);
  readonly entities = signal<EntityGroup[]>([]);

  ngOnInit(): void {
    this.route.queryParamMap.subscribe((params) => {
      const year = Number(params.get('year'));
      const month = Number(params.get('month'));
      if (year && month) {
        this.year.set(year);
        this.month.set(month);
      }
    });
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.errorMessage.set(null);
    this.api.getInvestmentLedger().subscribe({
      next: (data) => {
        this.entities.set(data);
        this.loading.set(false);
      },
      error: () => {
        this.errorMessage.set('No se pudo cargar el histórico de transacciones.');
        this.loading.set(false);
      },
    });
  }
}
