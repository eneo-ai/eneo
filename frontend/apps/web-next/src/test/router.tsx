/**
 * Test-only: renders UI inside a real TanStack Router, for tests of route
 * components and of the TanStack navigation (`src/lib/navigation.tanstack.ts`,
 * `src/lib/link.tanstack.tsx`). The router is the app's own
 * (`createAppRouter`: search serialization, trailing slash, scroll, pending
 * and error UI) on a memory history, inside `renderInApp`'s providers with
 * the same query client. Feature tests keep mocking the navigation instead
 * (`vi.mock("@/lib/navigation", () => import("@/test/navigation"))`).
 *
 * In vitest `@/lib/navigation` and `@/lib/link` are the Next modules, as in
 * the Next build. A test that needs the TanStack ones, such as an Astryx
 * link through the app's `LinkProvider`, swaps them:
 *
 *   vi.mock("@/lib/link", () => import("@/lib/link.tanstack"));
 *   vi.mock("@/lib/navigation", () => import("@/lib/navigation.tanstack"));
 */
import {
  createMemoryHistory,
  createRootRoute,
  Outlet,
  RouterProvider,
  type AnyRootRoute,
  type AnyRoute
} from "@tanstack/react-router";
import { act } from "@testing-library/react";
import { createTranslator } from "use-intl";
import messages from "@/lib/i18n/messages/sv.json";
import { createAppRouter } from "@/router";
import { renderInApp, testQueryClient, type RenderInAppOptions } from "./render";

export type RenderWithRouterOptions = Omit<RenderInAppOptions, "route"> & {
  /** Where the history starts, e.g. `/admin/users?page=2`. Default: `/`. */
  route?: string;
  /** Routes below the root, built on the root passed in; `ui` stays above them. */
  routes?: (root: AnyRootRoute) => AnyRoute[];
};

/**
 * Renders `ui` as the root route of a fresh router at `route`, once the
 * router has loaded. Returns the router, the query client and Testing
 * Library's result.
 *
 * @example
 * const { router } = await renderWithRouter(<Probe />, { route: "/admin/users?page=2" });
 * await renderWithRouter(<Nav />, {
 *   route: "/a",
 *   routes: (root) => [createRoute({ getParentRoute: () => root, path: "/a", component: A })]
 * });
 */
export async function renderWithRouter(
  ui: React.ReactNode,
  { route = "/", routes, queryClient = testQueryClient(), ...options }: RenderWithRouterOptions = {}
) {
  const root = createRootRoute({
    component: routes
      ? () => (
          <>
            {ui}
            <Outlet />
          </>
        )
      : () => ui
  });
  const router = createAppRouter(
    { queryClient, t: createTranslator({ locale: "sv", messages }) },
    {
      routeTree: routes ? root.addChildren(routes(root)) : root,
      history: createMemoryHistory({ initialEntries: [route] })
    }
  );
  const result = renderInApp(<RouterProvider router={router} />, { ...options, queryClient });
  await act(() => router.load());
  return { router, ...result };
}
