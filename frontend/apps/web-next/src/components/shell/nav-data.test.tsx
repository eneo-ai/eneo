// @vitest-environment jsdom
import { screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { SpacesList } from "@/features/spaces/list/spaces-list";
import { setRoute } from "@/test/navigation";
import { renderInApp, testQueryClient } from "@/test/render";
import { AppShellFrame } from "./app-shell";

// Cached navigation data must not start another request while still fresh.
const browserGet = vi.hoisted(() =>
  vi.fn<(_url: string) => Promise<never>>(() => new Promise(() => {}))
);
vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: browserGet } }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
// Stand-ins for the shell's bells (they have their own tests).
vi.mock("@/features/jobs/job-indicator", () => ({ JobIndicator: () => null }));
vi.mock("@/features/api-keys/expiring-keys-notification", () => ({
  ExpiringKeysNotification: () => null
}));
vi.mock("@/features/whats-new/whats-new-provider", () => ({
  useWhatsNew: () => ({ enabled: false, hasUnseen: false })
}));

beforeEach(() => {
  setRoute("/spaces/list");
  browserGet.mockClear();
});

it("shares prefetched spaces between the page and the shell's SideNav", () => {
  // The route and SideNav read the same query cache.
  const prefetched = testQueryClient();
  prefetched.setQueryData(
    ["spaces"],
    [{ id: "s1", name: "Upphandling", description: null, personal: false, organization: false }]
  );

  renderInApp(
    <AppShellFrame>
      <SpacesList title="Ytor" />
    </AppShellFrame>,
    { queryClient: prefetched }
  );

  expect(
    within(screen.getByRole("table", { name: "Ytor" }))
      .getByRole("link", { name: "Upphandling" })
      .getAttribute("href")
  ).toBe("/spaces/s1/overview");
  expect(browserGet.mock.calls.some(([url]) => url === "/api/v1/spaces/")).toBe(false);
});
