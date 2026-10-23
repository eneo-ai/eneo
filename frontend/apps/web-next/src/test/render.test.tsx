// @vitest-environment jsdom
import { Spinner } from "@astryxdesign/core/Spinner";
import { useQueryClient } from "@tanstack/react-query";
import { cleanup, screen } from "@testing-library/react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { afterEach, expect, it, vi } from "vitest";
import { useAppContext } from "@/components/providers/app-context";
import { useShell } from "@/components/shell/shell-context";
import { router } from "./navigation";
import { renderHookInApp, renderInApp, renderToHtml, testAppContext } from "./render";

vi.mock("next/navigation", () => import("@/test/navigation"));

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

it("starts every test at / with fresh router mocks", () => {
  const { result } = renderHookInApp(() => usePathname());
  expect(result.current).toBe("/");
  expect(router.push).not.toHaveBeenCalled();
});

it("renders what the server sends", () => {
  expect(renderToHtml(<Probe />, { route: "/dashboard" })).toContain(
    "Logga in | Anna Lind | no admin | /dashboard"
  );
});

it("merges overrides into each part of the app context", () => {
  const context = testAppContext({ tenant: { show_model_pricing: true } });
  expect(context.tenant).toMatchObject({
    display_name: "Sundsvalls kommun",
    show_model_pricing: true
  });
});
