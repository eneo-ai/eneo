// @vitest-environment jsdom
import { useSuspenseQuery } from "@tanstack/react-query";
import { createRoute, type AnyRootRoute } from "@tanstack/react-router";
import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import { renderWithRouter } from "@/test/router";

// As in the Vite build: the not-found page links home through TanStack.
vi.mock("@/lib/link", () => import("@/lib/link.tanstack"));

let loaders: { slow: () => Promise<void>; failing: () => Promise<void> };
let readData: () => Promise<string>;

beforeEach(() => {
  loaders = { slow: async () => {}, failing: async () => {} };
  readData = async () => "data";
  // A failed route logs its error (RouteError) and TanStack warns about it.
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.spyOn(console, "warn").mockImplementation(() => {});
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const routes = (root: AnyRootRoute) => [
  createRoute({ getParentRoute: () => root, path: "/", component: () => <h1>Start</h1> }),
  createRoute({
    getParentRoute: () => root,
    path: "/admin/users",
    component: () => <h1>Users</h1>
  }),
  createRoute({
    getParentRoute: () => root,
    path: "/slow",
    loader: () => loaders.slow(),
    component: () => <h1>Slow</h1>
  }),
  createRoute({
    getParentRoute: () => root,
    path: "/failing",
    loader: () => loaders.failing(),
    component: () => <h1>Loaded</h1>
  }),
  createRoute({
    getParentRoute: () => root,
    path: "/query",
    component: function QueryPage() {
      const { data } = useSuspenseQuery({ queryKey: ["page"], queryFn: () => readData() });
      return <h1>{data}</h1>;
    }
  })
];

async function renderRouter(route: string) {
  return (await renderWithRouter(null, { route, routes })).router;
}

it("drops a trailing slash and keeps the query", async () => {
  const router = await renderRouter("/admin/users/?page=2");

  expect(router.state.location.href).toBe("/admin/users?page=2");
  expect(router.history.location.href).toBe("/admin/users?page=2");
  expect(await screen.findByRole("heading", { name: "Users" })).toBeTruthy();
});

it("shows the not-found page for an address the app does not have", async () => {
  await renderRouter("/nowhere");

  expect(await screen.findByRole("heading", { name: "Sidan hittades inte" })).toBeTruthy();
  expect(screen.getByRole("link", { name: "Tillbaka till start" }).getAttribute("href")).toBe("/");
});

it("shows a failed load with its trace id, and its retry loads the route again", async () => {
  loaders.failing = async () => {
    throw new EneoApiError("Boom", { status: 500, traceId: "trace-1" });
  };
  const router = await renderRouter("/failing");
  const invalidate = vi.spyOn(router, "invalidate");

  expect(await screen.findByRole("heading", { name: "Något gick fel" })).toBeTruthy();
  expect(screen.getByText("Spårnings-ID: trace-1")).toBeTruthy();

  loaders.failing = async () => {};
  fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));

  expect(invalidate).toHaveBeenCalled();
  expect(await screen.findByRole("heading", { name: "Loaded" })).toBeTruthy();
});

it("lets a failed suspense query load again on retry", async () => {
  readData = async () => {
    throw new EneoApiError("Boom", { status: 500 });
  };
  await renderRouter("/query");
  expect(await screen.findByRole("heading", { name: "Något gick fel" })).toBeTruthy();

  readData = async () => "Fresh data";
  fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));

  expect(await screen.findByRole("heading", { name: "Fresh data" })).toBeTruthy();
});

it("shows the pending page only after a load has taken 200 ms", async () => {
  const router = await renderRouter("/");
  vi.useFakeTimers();
  let finish = () => {};
  loaders.slow = () => new Promise((resolve) => (finish = resolve));

  act(() => void router.navigate({ href: "/slow" }));
  await act(() => vi.advanceTimersByTimeAsync(150));
  expect(screen.queryByRole("status")).toBeNull();
  expect(screen.getByRole("heading", { name: "Start" })).toBeTruthy();

  await act(() => vi.advanceTimersByTimeAsync(100));
  expect(screen.getByRole("status")).toBeTruthy();

  finish();
  await act(() => vi.advanceTimersByTimeAsync(400));
  expect(screen.getByRole("heading", { name: "Slow" })).toBeTruthy();
});
