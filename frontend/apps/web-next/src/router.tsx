import type { QueryClient } from "@tanstack/react-query";
import {
  createRouter,
  useRouter,
  type AnyRoute,
  type ErrorComponentProps,
  type RouterHistory
} from "@tanstack/react-router";
import type { createTranslator } from "use-intl";
import { NotFoundPage } from "@/components/shell/not-found-page";
import { PagePending } from "@/components/shell/page-pending";
import { RouteError } from "@/components/shell/route-error";
import { bindNavigationRouter } from "@/lib/navigation";
import { parseSearch, stringifySearch } from "@/lib/router/search";
import { routeTree } from "./routeTree.gen";

/** What every route's `beforeLoad`, `loader` and `head` receive as `context`. */
export type RouterContext = {
  queryClient: QueryClient;
  /** The document's translator, for titles and other text outside React. */
  t: ReturnType<typeof createTranslator>;
};

/**
 * The Vite build's router, the one owner of its options. Tests pass their own
 * route tree and a memory history (src/test/router.tsx) and keep the rest.
 */
export function createAppRouter(
  context: RouterContext,
  overrides: { routeTree?: AnyRoute; history?: RouterHistory } = {}
) {
  const router = createRouter({
    // A test's tree is typed as the app's: only the app's routes are registered.
    routeTree: (overrides.routeTree ?? routeTree) as typeof routeTree,
    history: overrides.history,
    context,
    // Flat URLSearchParams (src/lib/router/search.ts), not TanStack's JSON.
    parseSearch,
    stringifySearch,
    // Canonical page paths omit a trailing slash: `/x/?q=1` → `/x?q=1`.
    trailingSlash: "never",
    // The page panel, not the window, is what scrolls (app-shell.tsx).
    scrollRestoration: true,
    scrollToTopSelectors: ["#main-content"],
    defaultPreload: "intent",
    // Loaders read through the query cache, which decides what is fresh.
    defaultPreloadStaleTime: 0,
    // Start values: no pending UI for a fast load, and none that flashes.
    // Retuned in P5 from measured p50/p95 loads against P0-baseline.
    defaultPendingMs: 200,
    defaultPendingMinMs: 400,
    defaultPendingComponent: PagePending,
    defaultErrorComponent: RouterRouteError,
    defaultNotFoundComponent: NotFoundPage
  });
  // replaceUrl() navigates outside React, with this router.
  bindNavigationRouter(router);
  return router;
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}

/** RouteError whose retry also runs the failed route's loaders again. */
function RouterRouteError({ error, reset }: ErrorComponentProps) {
  const router = useRouter();
  return (
    <RouteError
      error={error}
      reset={() => {
        void router.invalidate();
        reset();
      }}
    />
  );
}
