/**
 * The app's navigation (`@/lib/navigation`) on TanStack Router: the Vite build
 * aliases the seam to this module (vite.config.mts). Each export is typed
 * against the Next module, so `bun run check` fails when they drift.
 *
 * The hooks read the location on screen (`resolvedLocation`), not the one
 * still loading: while the next page loads, the current page keeps its path,
 * query and chrome.
 */
import {
  useRouter as useTanStackRouter,
  useRouterState,
  type AnyRouter,
  type ParsedLocation
} from "@tanstack/react-router";
import { useMemo } from "react";
import type * as Seam from "./navigation";

// The location on screen: the last one rendered while the next one loads.
const rendered = (state: { resolvedLocation?: ParsedLocation; location: ParsedLocation }) =>
  state.resolvedLocation ?? state.location;

// The path as the address bar has it (percent-encoded), as Next's usePathname
// returns it; TanStack's `pathname` is decoded.
export const usePathname: typeof Seam.usePathname = () =>
  useRouterState({ select: (state) => new URL(rendered(state).href, "http://n").pathname });

// One object per query, like Next's: effects that depend on it rerun only
// when the query changes.
export const useSearchParams: typeof Seam.useSearchParams = () => {
  const searchStr = useRouterState({ select: (state) => rendered(state).searchStr });
  return useMemo(() => new URLSearchParams(searchStr), [searchStr]);
};

export const useSpaceSegments: typeof Seam.useSpaceSegments = () =>
  usePathname().split("/").filter(Boolean).slice(2);

// `href` is an absolute app path or another site (`AppRouter`).
export const useRouter: typeof Seam.useRouter = () => {
  const router = useTanStackRouter();
  return useMemo(
    () => ({
      push: (href, options) =>
        void router.navigate({ href, resetScroll: options?.scroll !== false }),
      replace: (href, options) =>
        void router.navigate({ href, replace: true, resetScroll: options?.scroll !== false }),
      back: () => router.history.back(),
      refresh: () => void router.invalidate()
    }),
    [router]
  );
};

// replaceUrl is called outside React (an event handler's helper), so it needs
// the router instance itself; createAppRouter binds the app's router.
let boundRouter: AnyRouter | undefined;

export function bindNavigationRouter(router: AnyRouter): void {
  boundRouter = router;
}

/**
 * Updates the address in place, through the router so its hooks follow: no
 * history entry, no scroll reset, and the page stays mounted. `href` may be
 * relative to the current address (`?page=2`); another origin throws, as
 * `history.replaceState` does.
 */
export const replaceUrl: typeof Seam.replaceUrl = (href) => {
  const router = boundRouter;
  if (!router) throw new Error("replaceUrl() needs the app's router: createAppRouter binds it.");
  // Relative to the address the hooks report, as the page that calls it sees it.
  const { href: current } = rendered(router.state);
  const url = new URL(href, router.origin + current);
  if (url.origin !== router.origin) throw new Error(`replaceUrl() stays on this origin: ${url}`);
  void router.navigate({
    href: url.pathname + url.search + url.hash,
    replace: true,
    resetScroll: false
  });
};
