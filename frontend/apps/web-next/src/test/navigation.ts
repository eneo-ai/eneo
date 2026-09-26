/**
 * next/navigation for component tests. jsdom has no App Router, so a test
 * file that renders code using its hooks swaps the module for this one:
 *
 *   vi.mock("next/navigation", () => import("@/test/navigation"));
 *
 * The hooks then read the route the test set (`renderInApp(ui, { route })` or
 * `setRoute`), and `router` records where the app navigates. Both reset after
 * every test (src/test/setup-dom.ts).
 */
import { vi } from "vitest";

/** The route before a test sets one. */
const HOME = "/";

let url = new URL(HOME, "http://localhost");
// One object per route, like Next's: effects that depend on it rerun only
// when the route changes.
let searchParams = new URLSearchParams();

/** What `useRouter()` returns: every method is a `vi.fn()`. */
export const router = {
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
  for (const method of Object.values(router)) method.mockReset();
}

export function usePathname(): string {
  return url.pathname;
}

export function useSearchParams(): URLSearchParams {
  return searchParams;
}

export function useRouter(): typeof router {
  return router;
}
