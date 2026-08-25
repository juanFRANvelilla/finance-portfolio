import { Injectable } from '@angular/core';

export interface StoredPeriod {
  year: number;
  month: number;
}

const STORAGE_KEY = 'finance_portfolio_selected_period';
const MIN_YEAR = 2026;

@Injectable({ providedIn: 'root' })
export class PeriodStorageService {
  /** Lee el último mes/año visitado o devuelve el periodo por defecto (mes actual, mínimo 2026). */
  read(): StoredPeriod {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return this.defaultPeriod();

      const parsed = JSON.parse(raw) as Partial<StoredPeriod>;
      const year = Number(parsed.year);
      const month = Number(parsed.month);
      if (this.isValid(year, month)) {
        return { year, month };
      }
    } catch {
      // JSON corrupto o localStorage no disponible: usar valor por defecto.
    }
    return this.defaultPeriod();
  }

  /** Persiste el mes/año seleccionado para restaurarlo tras refrescar o navegar. */
  save(year: number, month: number): void {
    if (!this.isValid(year, month)) return;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ year, month }));
    } catch {
      // Ignorar si localStorage está bloqueado (modo privado, cuota, etc.).
    }
  }

  private defaultPeriod(): StoredPeriod {
    const now = new Date();
    return {
      year: Math.max(now.getFullYear(), MIN_YEAR),
      month: now.getMonth() + 1,
    };
  }

  private isValid(year: number, month: number): boolean {
    return Number.isInteger(year) && Number.isInteger(month) && year >= MIN_YEAR && month >= 1 && month <= 12;
  }
}
