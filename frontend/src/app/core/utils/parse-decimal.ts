/**
 * Convierte el valor de un input de texto a número.
 * Acepta coma o punto decimal y separadores de miles (p. ej. 15.000,50 o 15,000.50).
 */
export function parseDecimalInput(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === '') return null;

  let normalized = trimmed.replace(/\s/g, '');
  const hasComma = normalized.includes(',');
  const hasDot = normalized.includes('.');

  if (hasComma && hasDot) {
    if (normalized.lastIndexOf(',') > normalized.lastIndexOf('.')) {
      normalized = normalized.replace(/\./g, '').replace(',', '.');
    } else {
      normalized = normalized.replace(/,/g, '');
    }
  } else if (hasComma) {
    normalized = normalized.replace(',', '.');
  } else if (hasDot) {
    const parts = normalized.split('.');
    if (parts.length > 2) {
      normalized = `${parts.slice(0, -1).join('')}.${parts[parts.length - 1]}`;
    }
  }

  const parsed = Number(normalized);
  return Number.isNaN(parsed) ? null : parsed;
}

/** Muestra títulos en inputs con hasta 8 decimales (crypto), sin notación científica. */
export function formatUnitsForInput(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '';
  }
  const fixed = value.toFixed(8);
  return fixed.replace(/(\.\d*?[1-9])0+$/, '$1').replace(/\.0+$/, '');
}

export function formatAmountForInput(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '';
  }
  return String(value);
}
