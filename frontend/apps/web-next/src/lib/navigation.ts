/**
 * The app's navigation: code outside src/app reads the route and navigates
 * through this module, never through next/navigation. It is Next's App Router
 * now; the Vite build aliases this module to the TanStack Router
 * implementation, which implements the API below (`AppRouter`,
 * `ReadonlySearchParams`, and the functions' own types). Feature tests mock it:
 *
 *   vi.mock("@/lib/navigation", () => import("@/test/navigation"));
 */
import { usePathname } from "next/navigation";

// Next's hooks themselves, not wrappers: a test that mocks next/navigation
// reaches every caller through this module, and src/test/render.tsx checks
// which useRouter is in place by identity. Live re-exports also keep a partial
// next/navigation mock working until a missing hook is called.
// navigation.test.ts checks that they satisfy the types below.
export { useRouter, usePathname, useSearchParams } from "next/navigation";

export type NavigateOptions = {
  /** `false` keeps the scroll position; by default the page scrolls to the top. */
  scroll?: boolean;
};

/**
 * What `useRouter()` offers in both implementations. `href` is an absolute
 * app path with optional query and hash (`/x?tab=y`), never relative.
 */
export type AppRouter = {
  /** Navigates to `href` with a new history entry. */
  push(href: string, options?: NavigateOptions): void;
  /** Navigates to `href` in place of the current history entry. */
  replace(href: string, options?: NavigateOptions): void;
  back(): void;
  /** Reloads the route's data and keeps client state. */
  refresh(): void;
};

/** What `useSearchParams()` returns: the current query, read-only. */
export type ReadonlySearchParams = Omit<URLSearchParams, "append" | "delete" | "set" | "sort">;

/**
 * Puts `href` in the address bar in place of the current history entry,
 * without navigating: the page keeps its state, and the hooks report the new
 * address.
 */
export function replaceUrl(href: string | URL): void {
  window.history.replaceState(null, "", href);
}

/**
 * The path segments below `/spaces/[spaceId]`, as they appear in the URL:
 * `[]` for the space itself, `["knowledge", "collections", "c1"]` below it.
 */
export function useSpaceSegments(): string[] {
  return usePathname().split("/").filter(Boolean).slice(2);
}
