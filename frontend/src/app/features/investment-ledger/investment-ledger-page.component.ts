import { Component, inject, OnInit, signal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';

import { InvestmentApiService } from '../../core/services/investment-api.service';
import { PeriodStorageService } from '../../core/services/period-storage.service';
import { EntityGroup, TradeRepublicImportResult } from '../../core/models/ledger.model';
import { InvestmentLedgerComponent } from './investment-ledger.component';

/**
 * Página real de "Gestionar transacciones": carga el histórico completo de
 * entity_cash_flows + asset_transactions (agrupado por entidad) desde el backend.
 */
@Component({
  selector: 'app-investment-ledger-page',
  imports: [InvestmentLedgerComponent],
  templateUrl: './investment-ledger-page.component.html',
  styleUrl: './investment-ledger-page.component.scss',
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
  readonly importing = signal<boolean>(false);
  readonly importMessage = signal<string | null>(null);
  readonly importFailed = signal<boolean>(false);
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

  onImportCsv(file: File): void {
    const reader = new FileReader();
    reader.onload = () => {
      const csvText = String(reader.result ?? '');
      this.importing.set(true);
      this.importMessage.set(null);
      this.importFailed.set(false);
      this.api.importTradeRepublicCsv(csvText).subscribe({
        next: (result) => {
          this.importing.set(false);
          this.importMessage.set(this.formatImportResult(result));
          this.load();
        },
        error: (err: { error?: { detail?: string } }) => {
          this.importing.set(false);
          this.importFailed.set(true);
          this.importMessage.set(err?.error?.detail || 'No se pudo importar el CSV de Trade Republic.');
        },
      });
    };
    reader.onerror = () => {
      this.importFailed.set(true);
      this.importMessage.set('No se pudo leer el archivo.');
    };
    reader.readAsText(file);
  }

  private formatImportResult(result: TradeRepublicImportResult): string {
    const parts = [
      `Operaciones nuevas: ${result.inserted}`,
      `Ventas: ${result.sales_inserted}`,
      `Activos creados: ${result.assets_created}`,
      `Líquido ajustado: ${result.liquid_adjusted}`,
    ];
    if (result.skipped_duplicate) {
      parts.push(`Ya importadas: ${result.skipped_duplicate}`);
    }
    if (result.skipped_sell_without_asset) {
      parts.push(`Ventas sin activo de Trade Republic: ${result.skipped_sell_without_asset}`);
    }
    if (result.skipped_invalid_sell) {
      parts.push(`Ventas sin posición: ${result.skipped_invalid_sell}`);
    }
    if (result.messages.length) {
      parts.push(result.messages.join(' '));
    }
    return parts.join(' · ');
  }
}
