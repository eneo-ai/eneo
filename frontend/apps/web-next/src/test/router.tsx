/**
 * Test-only: renders UI inside a real TanStack Router, for tests of route
 * components and of the TanStack navigation (`src/lib/navigation.ts`,
 * `src/lib/link.tsx`). The router is the app's own
 * (`createAppRouter`: search serialization, trailing slash, scroll, pending
 * and error UI) on a memory history, inside `renderInApp`'s providers with
 * the same query client. Feature tests keep mocking the navigation instead
 * (`vi.mock("@/lib/navigation", () => import("@/test/navigation"))`).
 *
 * Component tests use plain anchors by default. Real-router tests enable
 * app links with vi.unmock("@/lib/link").
 */
import {
  createMemoryHistory,
  createRootRoute,
  Outlet,
  RouterProvider,
  type AnyRootRoute,
  type AnyRoute,
  type RouterHistory
} from "@tanstack/react-router";
import { act } from "@testing-library/react";
import { createContext, use } from "react";
import { createTranslator } from "use-intl";
import messages from "@/lib/i18n/messages/sv.json";
import { createAppRouter } from "@/router";
import { renderInApp, testQueryClient, type RenderInAppOptions } from "./render";

export type RenderWithRouterOptions = Omit<RenderInAppOptions, "route"> & {
  /** Where the history starts, e.g. `/admin/users?page=2`. Default: `/`. */
  route?: string;
  /** Supply browser history when exercising native popstate or beforeunload. */
  history?: RouterHistory;
  /** Routes below the root, built on the root passed in; `ui` stays above them. */
  routes?: (root: AnyRootRoute) => AnyRoute[];
};

// `ui` reaches the root route through context, so `rerender(ui)` changes it
// and keeps the router, its location and the query client.
const UiContext = createContext<React.ReactNode>(null);
const Ui = () => use(UiContext);

/**
 * Renders `ui` as the root route of a fresh router at `route`, once the
 * router has loaded. Returns the router, the query client and Testing
 * Library's result; `rerender(ui)` keeps the router.
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
  {
    route = "/",
    history,
    routes,
    queryClient = testQueryClient(),
    ...options
  }: RenderWithRouterOptions = {}
) {
  const root = createRootRoute({
    component: routes
      ? () => (
          <>
            <Ui />
            <Outlet />
          </>
        )
      : Ui
  });
  const router = createAppRouter(
    { queryClient, t: createTranslator({ locale: "sv", messages }) },
    {
      routeTree: routes ? root.addChildren(routes(root)) : root,
      history: history ?? createMemoryHistory({ initialEntries: [route] })
    }
  );
  const app = (node: React.ReactNode) => (
    <UiContext value={node}>
      <RouterProvider router={router} />
    </UiContext>
  );
  const result = renderInApp(app(ui), { ...options, queryClient });
  await act(() => router.load());
  return { router, ...result, rerender: (next: React.ReactNode) => result.rerender(app(next)) };
}
