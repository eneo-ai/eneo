/**
 * The app's navigation: code outside src/app reads the route and navigates
 * through this module, never through next/navigation. It is Next's App Router
 * now; the Vite build aliases this module to the TanStack Router
 * implementation, which is typed against the exports here, so the API holds
 * only what both routers honour. Feature tests mock it:
 *
 *   vi.mock("@/lib/navigation", () => import("@/test/navigation"));
 */
import {
  usePathname as nextUsePathname,
  useRouter as nextUseRouter,
  useSearchParams as nextUseSearchParams
} from "next/navigation";

import { useBeforeUnloadWarning } from "./hooks/use-before-unload-warning";

export type LeaveConfirmationState = {
  blocked: boolean;
  leave(): void;
  stay(): void;
};

/** During Next coexistence, keep its existing reload/tab-close protection. */
export const useLeaveConfirmation: (
  active: boolean,
  onLeave?: () => void
) => LeaveConfirmationState = (active) => {
  useBeforeUnloadWarning(active);
  return { blocked: false, leave() {}, stay() {} };
};

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

/** App-owned history metadata, separate from each router's internal state. */
export type UrlState = {
  /** A phone settings section has an index entry immediately behind it. */
  settingsSectionFromIndex?: boolean;
  /** Steps opened since the Flows list entry, for its “All steps” control. */
  flowStepDepth?: number;
};

export type UrlOptions = { state?: UrlState };

// Next's hooks themselves, not wrappers, typed down to the shared API: a test
// that mocks next/navigation reaches every caller through this module, and
// src/test/render.tsx checks which useRouter is in place by identity. They are
// read when this module loads, so a next/navigation mock must provide all
// three (spread `importOriginal()` into a partial one).
export const useRouter: () => AppRouter = nextUseRouter;
export const usePathname: () => string = nextUsePathname;
export const useSearchParams: () => ReadonlySearchParams = nextUseSearchParams;

/**
 * Puts `href` in the address bar in place of the current history entry,
 * without navigating: the page keeps its state, and the hooks report the new
 * address.
 */
export function replaceUrl(href: string | URL, options?: UrlOptions): void {
  const state: Record<string, unknown> = { ...window.history.state, ...options?.state };
  // Next copies its internals itself. Passing these markers bypasses its hook update.
  delete state.__NA;
  delete state._N;
  window.history.replaceState(state, "", href);
}

/** Opens an in-page view as a new history entry, keeping scroll and mounted state. */
export function pushUrl(href: string | URL, options?: UrlOptions): void {
  window.history.pushState(options?.state ?? null, "", href);
}

/** Traverses existing entries through the current router. */
export function goHistory(delta: number): void {
  window.history.go(delta);
}

/** Metadata of the entry currently shown; controls use it to choose Back or replace. */
export function readUrlState(): UrlState {
  return window.history.state ?? {};
}

/**
 * The path segments below `/spaces/[spaceId]`, as they appear in the URL:
 * `[]` for the space itself, `["knowledge", "collections", "c1"]` below it.
 */
export function useSpaceSegments(): string[] {
  return usePathname().split("/").filter(Boolean).slice(2);
}
