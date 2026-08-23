/**
 * Convierte el valor de un input de texto a número, aceptando tanto coma como punto
 * como separador decimal (los inputs nativos type="number" de Chrome solo aceptan
 * punto, lo que bloquea la coma habitual en España).
 */
export function parseDecimalInput(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === '') return null;

  const normalized = trimmed.replace(',', '.');
  const parsed = Number(normalized);
  return Number.isNaN(parsed) ? null : parsed;
}
