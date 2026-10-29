/**
 * The app's navigation (`@/lib/navigation`) on TanStack Router: the Vite build
 * aliases the seam to this module (vite.config.mts). Each export is typed
 * against the Next module, so `bun run check` fails when they drift.
 *
 * The hooks read the location of the page on screen: while the next page
 * loads, the current one keeps its path, query and chrome, and a new page
 * renders with its own address from its first render.
 */
import {
  useRouter as useTanStackRouter,
  type AnyRouter,
  type ParsedLocation
} from "@tanstack/react-router";
import { useMemo, useSyncExternalStore } from "react";
import type * as Seam from "./navigation";

declare module "@tanstack/react-router" {
  interface HistoryState {
    settingsSectionFromIndex?: Seam.UrlState["settingsSectionFromIndex"];
  }
}

type LocationStore = { get(): ParsedLocation; subscribe(listener: () => void): () => void };

const renderedLocations = new WeakMap<AnyRouter, LocationStore>();

/**
 * The location of the matches on screen. It changes when the router commits
 * a page (`onBeforeRouteMount`), in the same render as the page: the router's
 * `location` changes as a navigation starts, and its `resolvedLocation` only
 * after the new page has rendered once.
 */
function trackRenderedLocation(router: AnyRouter): LocationStore {
  let current = router.state.resolvedLocation ?? router.state.location;
  const listeners = new Set<() => void>();
  router.subscribe("onBeforeRouteMount", ({ toLocation }) => {
    current = toLocation;
    for (const listener of listeners) listener();
  });
  return {
    get: () => current,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    }
  };
}

function renderedLocation(router: AnyRouter): LocationStore {
  const store = renderedLocations.get(router);
  if (!store)
    throw new Error("The navigation hooks need the app's router: createAppRouter binds it.");
  return store;
}

function useRenderedLocation(select: (location: ParsedLocation) => string): string {
  const store = renderedLocation(useTanStackRouter());
  const read = () => select(store.get());
  return useSyncExternalStore(store.subscribe, read, read);
}

// The path as the address bar has it (percent-encoded), as Next's usePathname
// returns it; TanStack's `pathname` is decoded.
export const usePathname: typeof Seam.usePathname = () =>
  useRenderedLocation((location) => new URL(location.href, "http://n").pathname);

// One object per query, like Next's: effects that depend on it rerun only
// when the query changes.
export const useSearchParams: typeof Seam.useSearchParams = () => {
  const searchStr = useRenderedLocation((location) => location.searchStr);
  return useMemo(() => new URLSearchParams(searchStr), [searchStr]);
};

export const useSpaceSegments: typeof Seam.useSpaceSegments = () =>
  usePathname().split("/").filter(Boolean).slice(2);

/** `scroll: false` keeps the position: no reset to the top, no jump to a `#hash` target. */
export function scrollOptions(scroll: boolean | undefined) {
  return { resetScroll: scroll !== false, hashScrollIntoView: scroll !== false };
}

// `href` is an absolute app path or another site (`AppRouter`).
export const useRouter: typeof Seam.useRouter = () => {
  const router = useTanStackRouter();
  return useMemo(
    () => ({
      push: (href, options) => void router.navigate({ href, ...scrollOptions(options?.scroll) }),
      replace: (href, options) =>
        void router.navigate({ href, replace: true, ...scrollOptions(options?.scroll) }),
      back: () => router.history.back(),
      refresh: () => void router.invalidate()
    }),
    [router]
  );
};

// replaceUrl is called outside React (an event handler's helper), so it needs
// the router instance itself.
let boundRouter: AnyRouter | undefined;

/** Makes `router` the app's: the hooks follow its pages and replaceUrl navigates it. */
export function bindNavigationRouter(router: AnyRouter): void {
  if (!renderedLocations.has(router)) renderedLocations.set(router, trackRenderedLocation(router));
  boundRouter = router;
}

/**
 * Updates the address in place, through the router so its hooks follow: no
 * history entry, no scrolling, and the page stays mounted. `href` may be
 * relative to the current address (`?page=2`); another origin throws, as
 * `history.replaceState` does.
 */
function navigateUrl(href: string | URL, replace: boolean, options?: Seam.UrlOptions) {
  const router = boundRouter;
  if (!router) throw new Error("URL updates need the app's router: createAppRouter binds it.");
  // Relative to the address the hooks report, as the page that calls it sees it.
  const url = new URL(href, router.origin + renderedLocation(router).get().href);
  if (url.origin !== router.origin) throw new Error(`URL updates stay on this origin: ${url}`);
  void router.navigate({
    href: url.pathname + url.search + url.hash,
    replace,
    state: (current) => ({ ...(replace ? current : {}), ...options?.state }),
    ...scrollOptions(false)
  });
}

export const replaceUrl: typeof Seam.replaceUrl = (href, options) =>
  navigateUrl(href, true, options);
export const pushUrl: typeof Seam.pushUrl = (href, options) => navigateUrl(href, false, options);

export const readUrlState: typeof Seam.readUrlState = () => {
  if (!boundRouter) throw new Error("URL state needs the app's router: createAppRouter binds it.");
  return renderedLocation(boundRouter).get().state;
};
