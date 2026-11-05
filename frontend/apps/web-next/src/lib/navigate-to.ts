/**
 * Full-page navigation for routes that are not React pages (logout, SSO,
 * external): a client navigation, or a prefetching link, would run them.
 */
export function navigateTo(href: string, { replace = false }: { replace?: boolean } = {}): void {
  if (replace) window.location.replace(href);
  else window.location.assign(href);
}
