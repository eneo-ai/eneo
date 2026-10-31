// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp, testQueryClient } from "@/test/render";
import { setRoute } from "@/test/navigation";
import { setViewport } from "@/test/setup-dom";
import { AppDetail } from "./app-detail";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", () => ({ useSpace: () => ({ routeId: "space-1" }) }));
vi.mock("./run/run-view", () => ({ RunView: () => <p>Körvy</p> }));
vi.mock("./results/results-table", () => ({ ResultsTable: () => <p>Resultatvy</p> }));
afterEach(cleanup);

it("follows external same-route tab changes and falls back for an unknown tab", () => {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["apps", "app-1"], { name: "Protokoll", permissions: [] });
  const { rerender } = renderInApp(<AppDetail appId="app-1" />, {
    queryClient,
    route: "/spaces/space-1/apps/app-1"
  });
  // The run panel stays mounted behind Resultat, so name the one that is shown.
  const shown = () => {
    const [panel, ...more] = screen
      .getAllByRole("tabpanel")
      .filter((candidate) => candidate.getAttribute("data-state") === "active");
    expect(more).toEqual([]);
    return panel!;
  };
  expect(shown().textContent).toBe("Körvy");
  setRoute("/spaces/space-1/apps/app-1?tab=results");
  rerender(<AppDetail appId="app-1" />);
  expect(shown().textContent).toBe("Resultatvy");
  setRoute("/spaces/space-1/apps/app-1?tab=unknown");
  rerender(<AppDetail appId="app-1" />);
  expect(shown().textContent).toBe("Körvy");
});

it("offers Redigera as a pencil beside the name on a phone, and as a button elsewhere", () => {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["apps", "app-1"], { name: "Protokoll", permissions: ["edit"] });
  setViewport("phone");
  renderInApp(<AppDetail appId="app-1" />, { queryClient, route: "/spaces/space-1/apps/app-1" });
  const edit = screen.getByRole("link", { name: "Redigera" });
  expect(edit.getAttribute("href")).toBe("/spaces/space-1/apps/app-1/edit");
  expect(edit.textContent?.trim()).toBe("");
  cleanup();

  setViewport("tablet-portrait");
  renderInApp(<AppDetail appId="app-1" />, { queryClient, route: "/spaces/space-1/apps/app-1" });
  expect(screen.getByRole("link", { name: "Redigera" }).textContent).toContain("Redigera");
});
