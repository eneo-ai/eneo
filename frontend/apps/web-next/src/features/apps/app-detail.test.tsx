// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp, testQueryClient } from "@/test/render";
import { setRoute } from "@/test/navigation";
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
  expect(screen.getByRole("tabpanel").textContent).toBe("Körvy");
  setRoute("/spaces/space-1/apps/app-1?tab=results");
  rerender(<AppDetail appId="app-1" />);
  expect(screen.getByRole("tabpanel").textContent).toBe("Resultatvy");
  setRoute("/spaces/space-1/apps/app-1?tab=unknown");
  rerender(<AppDetail appId="app-1" />);
  expect(screen.getByRole("tabpanel").textContent).toBe("Körvy");
});
