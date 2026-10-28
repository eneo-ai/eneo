// @vitest-environment jsdom
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  HeadContent,
  Outlet,
  RouterProvider
} from "@tanstack/react-router";
import { act, render, waitFor } from "@testing-library/react";
import { createTranslator } from "use-intl";
import { beforeEach, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { testQueryClient } from "@/test/render";
import { createAppRouter } from "@/router";
import { RouteAnnouncer } from "./route-announcer";

const announce = vi.hoisted(() => vi.fn());
vi.mock("@astryxdesign/core/hooks", () => ({ useAnnounce: () => announce }));

beforeEach(() => announce.mockClear());

function routeTree() {
  const root = createRootRoute({
    component: () => (
      <>
        <HeadContent />
        <RouteAnnouncer />
        <Outlet />
      </>
    )
  });
  const page = (path: string, title: string) =>
    createRoute({
      getParentRoute: () => root,
      path,
      head: () => ({ meta: [{ title }] }),
      component: () => <h1>{title}</h1>
    });
  return root.addChildren([page("/a", "A · Eneo"), page("/b", "B · Eneo")]);
}

async function renderAt(route: string) {
  const router = createAppRouter(
    { queryClient: testQueryClient(), t: createTranslator({ locale: "sv", messages }) },
    { routeTree: routeTree(), history: createMemoryHistory({ initialEntries: [route] }) }
  );
  render(<RouterProvider router={router} />);
  await act(() => router.load());
  return router;
}

/** Lets the frame after a render run, where an announcement would be made. */
const nextFrame = () => act(() => new Promise((resolve) => requestAnimationFrame(resolve)));

it("announces nothing on the first page load", async () => {
  await renderAt("/a");
  await nextFrame();

  expect(document.title).toBe("A · Eneo");
  expect(announce).not.toHaveBeenCalled();
});

it("announces the new page's title once, without moving focus", async () => {
  const router = await renderAt("/a");

  await act(() => router.navigate({ to: "/b" }));

  await waitFor(() => expect(announce).toHaveBeenCalledWith("B · Eneo"));
  await nextFrame();
  expect(announce).toHaveBeenCalledTimes(1);
  expect(document.activeElement).toBe(document.body);
});

it("announces nothing when only the query changes", async () => {
  const router = await renderAt("/a");

  await act(() => router.navigate({ to: "/a", search: { x: "1" } }));
  await nextFrame();

  expect(router.state.location.href).toBe("/a?x=1");
  expect(announce).not.toHaveBeenCalled();
});
