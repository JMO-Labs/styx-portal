/** Thin wrapper over location assignment so custom-scheme launches are mockable in tests. */
export function navigateTo(url: string): void {
  window.location.href = url;
}
