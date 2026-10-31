/**
 * App-owned navigation on TanStack Router. Feature tests can replace this
 * module with @/test/navigation; route tests use the real router.
 *
 * The hooks read the location of the page on screen: while the next page
 * loads, the current one keeps its path, query and chrome, and a new page
 * renders with its own address from its first render.
 */
import {
  useRouter as useTanStackRouter,
  useBlocker,
  type AnyRouter,
  type ParsedLocation
} from "@tanstack/react-router";
import { useEffect, useEffectEvent, useMemo, useRef, useSyncExternalStore } from "react";
export type LeaveConfirmationState = {
  blocked: boolean;
  leave(): void;
  stay(): void;
};

export type NavigateOptions = {
  /** `false` keeps the scroll position; by default the page scrolls to the top. */
  scroll?: boolean;
};

/**
 * The application navigation API. `href` is an absolute
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
};

export type UrlOptions = {
  state?: UrlState;
  /** Metadata for the already displayed view, such as a newly assigned session id. */
  ignoreBlocker?: boolean;
};

import { stringifySearch } from "./router/search";

declare module "@tanstack/react-router" {
  interface HistoryState {
    settingsSectionFromIndex?: UrlState["settingsSectionFromIndex"];
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
  return useSyncExternalStore(store.subscribe, read);
}

// The percent-encoded path from the address bar; TanStack pathname is decoded.
export const usePathname: () => string = () =>
  useRenderedLocation((location) => new URL(location.href, "http://n").pathname);

// One object per query: effects that depend on it rerun only
// when the query changes.
export const useSearchParams: () => ReadonlySearchParams = () => {
  const searchStr = useRenderedLocation((location) => location.searchStr);
  return useMemo(() => new URLSearchParams(searchStr), [searchStr]);
};

export const useSpaceSegments: () => string[] = () =>
  usePathname().split("/").filter(Boolean).slice(2);

/** `scroll: false` keeps the position: no reset to the top, no jump to a `#hash` target. */
export function scrollOptions(scroll: boolean | undefined) {
  return { resetScroll: scroll !== false, hashScrollIntoView: scroll !== false };
}

// `href` is an absolute app path or another site (`AppRouter`).
export const useRouter: () => AppRouter = () => {
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
function navigateUrl(href: string | URL, replace: boolean, options?: UrlOptions) {
  const router = boundRouter;
  if (!router) throw new Error("URL updates need the app's router: createAppRouter binds it.");
  // Relative to the address the hooks report, as the page that calls it sees it.
  const url = new URL(href, router.origin + renderedLocation(router).get().href);
  if (url.origin !== router.origin) throw new Error(`URL updates stay on this origin: ${url}`);
  void router.navigate({
    href: url.pathname + url.search + url.hash,
    replace,
    ignoreBlocker: options?.ignoreBlocker,
    state: (current) => ({ ...(replace ? current : {}), ...options?.state }),
    ...scrollOptions(false)
  });
}

export const replaceUrl: (href: string | URL, options?: UrlOptions) => void = (href, options) =>
  navigateUrl(href, true, options);
export const pushUrl: (href: string | URL, options?: UrlOptions) => void = (href, options) =>
  navigateUrl(href, false, options);

export const readUrlState: () => UrlState = () => {
  if (!boundRouter) throw new Error("URL state needs the app's router: createAppRouter binds it.");
  return renderedLocation(boundRouter).get().state;
};

/** The router keeps the pending transition, including its history action and fragment. */
export const useLeaveConfirmation: (
  active: boolean,
  onLeave?: () => void
) => LeaveConfirmationState = (active, onLeave) => {
  const router = useTanStackRouter();
  const departureAccepted = useRef(false);
  useEffect(
    () =>
      router.subscribe("onResolved", () => {
        departureAccepted.current = false;
      }),
    [router]
  );
  const blocker = useBlocker({
    shouldBlockFn: ({ current, next }) => {
      const leaving =
        current.pathname !== next.pathname ||
        stringifySearch(current.search) !== stringifySearch(next.search);
      if (leaving) departureAccepted.current = false;
      return active && leaving;
    },
    withResolver: true,
    // A confirmed SPA departure also covers a recovery reload while its route loads.
    enableBeforeUnload: () => active && !departureAccepted.current
  });
  const leave = () => {
    if (blocker.proceed) {
      onLeave?.();
      departureAccepted.current = true;
      blocker.proceed();
    }
  };
  const releasePending = useEffectEvent(leave);
  // Saved or removed editors no longer need a decision about their edits.
  // Release the latest native transition, including on actual guard teardown.
  useEffect(() => {
    if (!active) releasePending();
  }, [active, blocker.proceed]);
  useEffect(() => () => releasePending(), []);
  return {
    blocked: blocker.status === "blocked",
    leave,
    stay: () => blocker.reset?.()
  };
};
