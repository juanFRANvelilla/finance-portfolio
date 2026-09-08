import { Component, effect, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ImportPayload } from '../../../../core/models/monthly-record.model';
import { MONTH_NAMES } from '../../../../core/models/month-names';

@Component({
  selector: 'app-json-import-dialog',
  imports: [FormsModule],
  templateUrl: './json-import-dialog.component.html',
  styleUrl: './json-import-dialog.component.scss',
})
export class JsonImportDialogComponent {
  readonly open = input.required<boolean>();
  readonly year = input.required<number>();
  readonly month = input.required<number>();
  readonly importing = input<boolean>(false);
  readonly errorMessage = input<string | null>(null);

  readonly close = output<void>();
  readonly importPayload = output<ImportPayload>();

  readonly monthNames = MONTH_NAMES;
  readonly jsonText = signal('');
  readonly parseError = signal<string | null>(null);

  constructor() {
    effect(() => {
      if (this.open()) {
        this.resetForm();
      }
    });
  }

  private resetForm(): void {
    this.jsonText.set('');
    this.parseError.set(null);
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) {
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      this.jsonText.set(String(reader.result ?? ''));
      this.parseError.set(null);
    };
    reader.readAsText(file);
    input.value = '';
  }

  onImport(): void {
    this.parseError.set(null);

    let parsed: unknown;
    try {
      parsed = JSON.parse(this.jsonText());
    } catch {
      this.parseError.set('El JSON no es válido. Revisa la sintaxis.');
      return;
    }

    const validationError = this.validatePayload(parsed);
    if (validationError) {
      this.parseError.set(validationError);
      return;
    }

    this.importPayload.emit(parsed as ImportPayload);
  }

  onClose(): void {
    this.resetForm();
    this.close.emit();
  }

  loadExample(): void {
    this.jsonText.set(
      JSON.stringify(
        {
          simple_balances: [
            { entity_id: 'sabadell', amount: 11116.0 },
            { entity_id: 'santander', amount: 2430.0 },
            { entity_id: 'kucoin', amount: 3305.0 },
          ],
          hybrid_balances: [
            { entity_id: 'trade_republic', liquid_amount: 630.42, invested_amount: 0.0 },
            { entity_id: 'myinvestor', liquid_amount: 2825.0, invested_amount: 5797.0 },
          ],
          expected_totals: {
            total_liquid: 17001.42,
            total_invested: 9102.0,
            total_net_worth: 26103.42,
          },
        },
        null,
        2,
      ),
    );
    this.parseError.set(null);
  }

  private validatePayload(value: unknown): string | null {
    if (!value || typeof value !== 'object') {
      return 'El payload debe ser un objeto JSON.';
    }

    const payload = value as Record<string, unknown>;

    if (!Array.isArray(payload['simple_balances'])) {
      return 'Falta simple_balances (array).';
    }
    if (!Array.isArray(payload['hybrid_balances'])) {
      return 'Falta hybrid_balances (array).';
    }
    if (!payload['expected_totals'] || typeof payload['expected_totals'] !== 'object') {
      return 'Falta expected_totals (objeto).';
    }

    const totals = payload['expected_totals'] as Record<string, unknown>;
    for (const key of ['total_liquid', 'total_invested', 'total_net_worth']) {
      if (typeof totals[key] !== 'number') {
        return `expected_totals.${key} debe ser numérico.`;
      }
    }

    return null;
  }
}
