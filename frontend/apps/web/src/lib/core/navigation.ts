/**
 * Full-document navigation to a URL outside the SvelteKit router, such as a
 * signed download link.
 *
 * Browser-mode component tests must mock this module: a real navigation
 * unloads the Vitest tester iframe, and the run then hangs instead of failing.
 */
export function assignLocation(url: string): void {
  window.location.assign(url);
}
