/**
 * Full-page navigation for routes that are not React pages (logout, SSO,
 * external): a client navigation, or a prefetching link, would run them.
 */
export function navigateTo(href: string): void {
  window.location.assign(href);
}
