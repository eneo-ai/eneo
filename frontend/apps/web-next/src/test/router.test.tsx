// @vitest-environment jsdom
import { createRoute, useRouterState } from "@tanstack/react-router";
import { screen } from "@testing-library/react";
import { useTranslations } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useAppContext } from "@/components/providers/app-context";
import { renderWithRouter } from "./router";

afterEach(() => vi.restoreAllMocks());

function Pathname() {
  return <p>{useRouterState({ select: (state) => state.location.pathname })}</p>;
}

it("loads the route with the app's router options", async () => {
  const { router } = await renderWithRouter(<Pathname />, { route: "/admin/users/?page=2" });

  expect(screen.getByText("/admin/users")).toBeTruthy();
  expect(router.state.location.href).toBe("/admin/users?page=2");
});

it("reads the query flat: strings, and a list for a repeated key", async () => {
  const { router } = await renderWithRouter(null, { route: "/x?page=2&tab=a&tab=b" });

  expect(router.state.location.search).toEqual({ page: "2", tab: ["a", "b"] });
});

it("renders in the app's providers", async () => {
  function Probe() {
    const t = useTranslations();
    const { user } = useAppContext();
    return <p>{`${t("login")} | ${user.username}`}</p>;
  }

  await renderWithRouter(<Probe />);

  expect(screen.getByText("Logga in | Anna Lind")).toBeTruthy();
});

it("renders routes below the UI", async () => {
  await renderWithRouter(<p>Above</p>, {
    route: "/a",
    routes: (root) => [
      createRoute({ getParentRoute: () => root, path: "/a", component: () => <h1>Page A</h1> })
    ]
  });

  expect(screen.getByText("Above")).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Page A" })).toBeTruthy();
});

it("rerenders the UI in the same router", async () => {
  function Greeting({ name }: { name: string }) {
    return <p>{`${name} ${useRouterState({ select: (state) => state.location.href })}`}</p>;
  }
  const { router, queryClient, rerender } = await renderWithRouter(<Greeting name="Anna" />, {
    route: "/a?tab=x"
  });
  queryClient.setQueryData(["seed"], "planted");

  rerender(<Greeting name="Bo" />);

  expect(screen.getByText("Bo /a?tab=x")).toBeTruthy();
  expect(router.state.location.href).toBe("/a?tab=x");
  expect(queryClient.getQueryData(["seed"])).toBe("planted");
});

describe("isolation", () => {
  let first: { router: unknown; queryClient: unknown } | undefined;

  it("starts a router and a query client", async () => {
    const { router, queryClient } = await renderWithRouter(null, { route: "/first" });
    queryClient.setQueryData(["seed"], "planted");
    first = { router, queryClient };
  });

  it("gives the next test new ones", async () => {
    const { router, queryClient } = await renderWithRouter(null);

    expect(router).not.toBe(first?.router);
    expect(queryClient).not.toBe(first?.queryClient);
    expect(queryClient.getQueryData(["seed"])).toBeUndefined();
    expect(router.state.location.pathname).toBe("/");
  });
});
