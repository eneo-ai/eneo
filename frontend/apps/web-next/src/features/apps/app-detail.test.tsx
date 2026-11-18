// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { renderInApp, testQueryClient } from "@/test/render";
import { setRoute } from "@/test/navigation";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import type { Space } from "@/features/spaces/space";
import { expectNoAxeViolations } from "@/test/axe";
import { setViewport } from "@/test/setup-dom";
import { AppDetail } from "./app-detail";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
const state = vi.hoisted(() => ({ space: null as unknown as Space }));
vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({ routeId: "space-1", space: state.space })
}));
vi.mock("./run/run-view", () => ({ RunView: () => <p>Körvy</p> }));
vi.mock("./results/results-table", () => ({ ResultsTable: () => <p>Resultatvy</p> }));
afterEach(cleanup);
beforeEach(() => {
  state.space = makeSpace({
    apps: [
      { id: "app-1", name: "Protokoll" },
      { id: "app-2", name: "Sammanfattning" }
    ]
  });
});

it("follows external same-route tab changes and falls back for an unknown tab", () => {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["apps", "app-1"], { id: "app-1", name: "Protokoll", permissions: [] });
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
  expect(screen.queryByRole("link", { name: "Redigera" })).toBeNull();
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

it.each([false, true])(
  "keeps naming the open app with no choices (applications unavailable=%s)",
  async (unavailable) => {
    state.space = makeSpace({ apps: [], overrides: unavailable ? { applications: null } : {} });
    const queryClient = testQueryClient();
    queryClient.setQueryData(["apps", "app-1"], {
      id: "app-1",
      name: "Protokoll",
      permissions: []
    });
    renderInApp(<AppDetail appId="app-1" />, { queryClient, route: "/spaces/space-1/apps/app-1" });
    expect(screen.getByRole("heading", { level: 1, name: "Protokoll" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Välj en app" }));
    const choices = await screen.findByRole("dialog", { name: "Välj en app" });
    expect(within(choices).getByText("Inga resultat hittades")).toBeTruthy();
    expect(within(choices).queryByRole("link")).toBeNull();
  }
);

it("keeps the title as a heading and switches to a same-space app's normal run URL", async () => {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["apps", "app-1"], {
    id: "app-1",
    name: "Protokoll",
    permissions: ["edit"]
  });
  renderInApp(<AppDetail appId="app-1" />, {
    queryClient,
    route: "/spaces/space-1/apps/app-1?tab=results"
  });
  expect(screen.getByRole("heading", { level: 1, name: "Protokoll" })).toBeTruthy();
  expect(screen.getByRole("link", { name: "Redigera" }).getAttribute("href")).toBe(
    "/spaces/space-1/apps/app-1/edit"
  );
  fireEvent.click(screen.getByRole("button", { name: "Välj en app" }));
  const choices = await screen.findByRole("dialog", { name: "Välj en app" });
  const current = within(choices).getByRole("link", { name: "Protokoll" });
  expect(current.getAttribute("aria-current")).toBe("page");
  const other = within(choices).getByRole("link", { name: "Sammanfattning" });
  expect(other.getAttribute("href")).toBe("/spaces/space-1/apps/app-2");
  await expectNoAxeViolations(document.body);
  other.addEventListener("click", (event) => event.preventDefault(), { once: true });
  fireEvent.click(other);
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Välj en app" })).toBeNull());
});
