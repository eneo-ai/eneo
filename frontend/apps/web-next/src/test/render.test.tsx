// @vitest-environment jsdom
import { Spinner } from "@astryxdesign/core/Spinner";
import { useQueryClient } from "@tanstack/react-query";
import { act, cleanup, screen } from "@testing-library/react";
import { usePathname, useRouter, useSearchParams } from "@/lib/navigation";
import { useTranslations } from "use-intl";
import { afterEach, expect, it, vi } from "vitest";
import { useAppContext } from "@/components/providers/app-context";
import { useShell } from "@/components/shell/shell-context";
import { Link, replaceUrl, router } from "./navigation";
import { renderHookInApp, renderInApp, testAppContext } from "./render";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));

afterEach(cleanup);

/** What a page in the app reads from its providers. */
function Probe() {
  const t = useTranslations();
  const { user, can } = useAppContext();
  const queryClient = useQueryClient();
  const pathname = usePathname();
  const tab = useSearchParams().get("tab");
  useShell();
  return (
    <p>
      {[
        t("login"),
        user.username,
        can("admin") ? "admin" : "no admin",
        pathname,
        tab,
        queryClient.getDefaultOptions().queries?.staleTime
      ].join(" | ")}
    </p>
  );
}

it("renders in Swedish, Astryx's own strings too", () => {
  renderInApp(<Spinner />);
  expect(screen.getByRole("status", { name: "Läser in" })).toBeTruthy();
});

it("provides the signed-in context, the app's query client, the shell and the route", () => {
  renderInApp(<Probe />, {
    route: "/spaces/s1/knowledge?tab=websites",
    appContext: testAppContext({ permissions: ["admin"] })
  });
  expect(
    screen.getByText("Logga in | Anna Lind | admin | /spaces/s1/knowledge | websites | 30000")
  ).toBeTruthy();
});

it("records where the app navigates", () => {
  const { result } = renderHookInApp(() => useRouter(), { route: "/spaces/list" });
  result.current.push("/dashboard");
  expect(router.push).toHaveBeenCalledWith("/dashboard");
});

it("moves the route with replaceUrl and rerenders, as the app does", () => {
  renderInApp(<Probe />, { route: "/spaces/s1/knowledge?tab=websites" });
  act(() => replaceUrl("/a?tab=x"));
  expect(screen.getByText("Logga in | Anna Lind | no admin | /a | x | 30000")).toBeTruthy();
  expect(window.location.pathname + window.location.search).toBe("/a?tab=x");
});

it("links with a plain anchor, without the router's options", () => {
  renderInApp(
    <Link href="/a?tab=x" prefetch={false} replace>
      A
    </Link>
  );
  const link = screen.getByRole("link", { name: "A" });
  expect(link.outerHTML).toBe('<a href="/a?tab=x">A</a>');
});

it("starts every test at / with fresh router mocks", () => {
  const { result } = renderHookInApp(() => usePathname());
  expect(result.current).toBe("/");
  expect(router.push).not.toHaveBeenCalled();
});

it("merges overrides into each part of the app context", () => {
  const context = testAppContext({ tenant: { show_model_pricing: true } });
  expect(context.tenant).toMatchObject({
    display_name: "Sundsvalls kommun",
    show_model_pricing: true
  });
});

// Last: it unmocks the navigation for the rest of this file.
it("asks for the navigation mock when a test sets a route without it", async () => {
  vi.doUnmock("@/lib/navigation");
  vi.resetModules();
  const { renderInApp: renderUnmocked } = await import("./render");
  expect(() => renderUnmocked(<p />, { route: "/x" })).toThrow(
    'renderInApp({ route }) needs vi.mock("@/lib/navigation", () => import("@/test/navigation")).'
  );
});
