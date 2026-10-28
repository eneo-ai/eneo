/**
 * The app's navigation (`@/lib/navigation`) for component tests. jsdom has no
 * router, so a test file that renders code using it swaps the module for this
 * one:
 *
 *   vi.mock("@/lib/navigation", () => import("@/test/navigation"));
 *
 * (src/app code still imports next/navigation: mock that with this module.)
 *
 * The hooks then read the route the test set (`renderInApp(ui, { route })` or
 * `setRoute`), and `router` records where the app navigates. Both reset after
 * every test (src/test/setup-dom.ts). `replaceUrl` rerenders the hooks' users,
 * as both routers do; after `setRoute`, rerender yourself.
 *
 * A route component, or the TanStack navigation itself, is tested in a real
 * router instead: `renderWithRouter` (src/test/router.tsx).
 */
import { createElement, useSyncExternalStore } from "react";
import { vi } from "vitest";
import type { LinkProps } from "@/lib/link";

/** The route before a test sets one. */
const HOME = "/";

let url = new URL(HOME, "http://localhost");
// One object per route, like Next's: effects that depend on it rerun only
// when the route changes.
let searchParams = new URLSearchParams();

/** What `useRouter()` returns: every method is a `vi.fn()`. */
export const router = {
  bfcacheId: "test-route",
  push: vi.fn(),
  replace: vi.fn(),
  refresh: vi.fn(),
  prefetch: vi.fn(),
  back: vi.fn(),
  forward: vi.fn()
};

/**
 * Sets the current route: a path with an optional query. Call it before
 * rendering, or rerender afterwards (the App Router rerenders on navigation).
 *
 * @example setRoute("/spaces/s1/knowledge?tab=websites");
 */
export function setRoute(route: string): void {
  url = new URL(route, "http://localhost");
  searchParams = new URLSearchParams(url.search);
}

/** Back to `/` with fresh router mocks. */
export function resetNavigation(): void {
  setRoute(HOME);
  for (const method of Object.values(router)) {
    if (vi.isMockFunction(method)) method.mockReset();
  }
  replaceUrl.mockClear();
}

const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const readPathname = () => url.pathname;
const readSearchParams = () => searchParams;

export function usePathname(): string {
  return useSyncExternalStore(subscribe, readPathname, readPathname);
}

export function useSearchParams(): URLSearchParams {
  return useSyncExternalStore(subscribe, readSearchParams, readSearchParams);
}

export function useRouter(): typeof router {
  return router;
}

/** Puts `href` in the address bar, as the app's `replaceUrl` does, and reports it as the route. */
export const replaceUrl = vi.fn((href: string | URL) => {
  const next = new URL(href, url);
  const route = next.pathname + next.search;
  setRoute(route);
  // The path, not `next`: jsdom's origin is not this module's base URL.
  if (typeof window !== "undefined") window.history.replaceState(null, "", route + next.hash);
  for (const listener of listeners) listener();
});

export function useSpaceSegments(): string[] {
  return url.pathname.split("/").filter(Boolean).slice(2);
}

/** A plain anchor for `@/lib/link`: its router options do nothing here. */
export function Link(props: LinkProps) {
  const anchor = { ...props };
  delete anchor.prefetch;
  delete anchor.scroll;
  delete anchor.replace;
  return createElement("a", anchor);
}
