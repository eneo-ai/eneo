// SvelteKit's shallow `replaceState` changes the address bar and `page.state`,
// never `page.url`. A mock that rewrites `page.url` hides code that reads a stale
// URL, so this stand-in writes the address bar instead. Vitest's own frame query
// (session and frame ids) and path stay, or the frame could no longer report.
const frameUrl = new URL(location.href);

export function replaceShallowState(
  route: { state: unknown },
  url: URL | string,
  state: unknown
): void {
  const next = new URL(url, location.href);
  const address = new URL(frameUrl);
  for (const [key, value] of next.searchParams) {
    if (!frameUrl.searchParams.has(key)) address.searchParams.append(key, value);
  }
  history.replaceState(history.state, "", address);
  route.state = state;
}

/** The query string the address bar shows now. */
export function addressParams(): URLSearchParams {
  return new URL(location.href).searchParams;
}

export function restoreFrameUrl(): void {
  history.replaceState(history.state, "", frameUrl);
}
