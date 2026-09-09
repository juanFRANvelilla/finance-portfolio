import { Component, inject, OnInit, signal } from '@angular/core';

import { InvestmentApiService } from '../../core/services/investment-api.service';
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

  readonly loading = signal<boolean>(false);
  readonly errorMessage = signal<string | null>(null);
  readonly entities = signal<EntityGroup[]>([]);

  ngOnInit(): void {
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
