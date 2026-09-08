/** Lee una custom property CSS del elemento (p. ej. `:host` del componente). */
export function readCssVar(element: HTMLElement, name: string, fallback: string): string {
  const value = getComputedStyle(element).getPropertyValue(name).trim();
  return value || fallback;
}
