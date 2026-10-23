// @vitest-environment jsdom
import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { SpacesList } from "@/app/(app)/spaces/list/spaces-list.client";
import { setRoute } from "@/test/navigation";
import { renderToHtml, testQueryClient } from "@/test/render";
import { AppShellFrame } from "./app-shell";

// The browser's API client has a relative base URL ("/api/eneo"): during the
// server render it cannot reach the backend ("Failed to parse URL").
const browserGet = vi.hoisted(() => vi.fn(() => new Promise(() => {})));
vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: browserGet } }));
vi.mock("next/navigation", () => import("@/test/navigation"));
// Stand-ins for the shell's bells (they have their own tests).
vi.mock("@/features/jobs/job-indicator", () => ({ JobIndicator: () => null }));
vi.mock("@/features/api-keys/expiring-keys-notification", () => ({
  ExpiringKeysNotification: () => null
}));
vi.mock("@/features/whats-new/whats-new-provider", () => ({
  useWhatsNew: () => ({ enabled: false, hasUnseen: false })
}));
vi.mock("@/lib/i18n/actions", () => ({ setLocale: vi.fn() }));

beforeEach(() => {
  setRoute("/spaces/list");
  browserGet.mockClear();
});

it("server-renders the spaces a page prefetched, under the shell's SideNav", () => {
  // /spaces/list prefetches the list with the server's client and dehydrates
  // it; the SideNav also shows spaces, loaded in the browser.
  const prefetched = testQueryClient();
  prefetched.setQueryData(
    ["spaces"],
    [{ id: "s1", name: "Upphandling", description: null, personal: false, organization: false }]
  );

  const html = renderToHtml(
    <AppShellFrame>
      <HydrationBoundary state={dehydrate(prefetched)}>
        <SpacesList title="Ytor" />
      </HydrationBoundary>
    </AppShellFrame>,
    { queryClient: testQueryClient() }
  );

  expect(html).toContain('aria-label="Upphandling"');
  expect(browserGet).not.toHaveBeenCalled();
});
