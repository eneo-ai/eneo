// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { router, setRoute } from "@/test/navigation";
import { renderInApp } from "@/test/render";
import type { Space } from "@/features/spaces/space";

const state = vi.hoisted(() => ({ space: null as unknown, deleted: [] as string[] }));

vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space as Space) };
});
vi.mock("@/features/jobs/use-jobs", () => ({
  useJobs: () => ({ trackJob: () => {}, queueUploads: () => {} })
}));
vi.mock("@/lib/api/browser", async () => {
  const { makeSpace } = await import("@/features/spaces/testing/space-fixture");
  const ok = (data: unknown, status = 200) =>
    Promise.resolve({ data, response: new Response(null, { status }) });
  return {
    browserApi: {
      GET: (path: string) =>
        ok(
          path.endsWith("/documents/skipped/")
            ? { items: [], total: 0, truncated: false, synced_at: null }
            : path.endsWith("/documents/")
              ? { items: [], total_count: 0, limit: 50, offset: 0, total_size: 0 }
              : { items: [] }
        ),
      DELETE: (path: string) => {
        state.deleted.push(path);
        // What the space holds once the item is gone.
        state.space = makeSpace();
        return ok(null, 204);
      }
    }
  };
});

import { makeIntegration, makeSpace } from "@/features/spaces/testing/space-fixture";
import { ItemDetail } from "./item-detail.client";

afterEach(() => {
  cleanup();
  state.deleted = [];
});

function show(fields: Record<string, unknown> = {}) {
  state.space = makeSpace({
    integrations: [
      makeIntegration({
        id: "i1",
        name: "Avtal",
        selected_item_type: "file",
        permissions: ["read", "edit", "delete"],
        metadata: { size: 0, last_synced_at: "2026-10-14T08:00:00Z", document_count: 1 },
        ...fields
      })
    ]
  });
  setRoute("/spaces/space-1/knowledge/integrations/i1");
  return renderInApp(<ItemDetail itemId="i1" />);
}

describe("ItemDetail", () => {
  it("shows the item as its own source, with the vendor named next to its logo", async () => {
    const { container } = show();

    expect(screen.getByRole("heading", { level: 1, name: "Avtal" })).toBeTruthy();
    // The logo is decoration; the vendor's name is text everyone gets.
    expect(container.querySelector("img")?.getAttribute("alt")).toBe("");
    const vendor = screen.getByText("SharePoint");
    expect(vendor.parentElement?.querySelector("img")).toBeTruthy();
    expect(vendor.parentElement?.textContent).toContain("1 fil");
    expect(screen.getByRole("link", { name: /Öppna i SharePoint/ }).getAttribute("href")).toBe(
      "https://kommun.sharepoint.com/sites/avtal"
    );
    await expectNoAxeViolations(container);
  });

  it("names Confluence for a page imported from Confluence", () => {
    show({ integration_type: "confluence", selected_item_type: "page" });
    expect(screen.getByText("Confluence")).toBeTruthy();
  });

  it("offers no link to an address at the source that is not https", () => {
    show({ url: "http://kommun.sharepoint.com/sites/avtal" });
    expect(screen.queryByRole("link", { name: /Öppna i SharePoint/ })).toBeNull();
    expect(document.querySelector('a[href^="http:"]')).toBeNull();
  });

  it("replaces the page with the list once the item was deleted from it", async () => {
    show();
    const notFound: boolean[] = [];
    const observer = new MutationObserver(() =>
      notFound.push(screen.queryByText("Inga resultat hittades") !== null)
    );
    observer.observe(document.body, { childList: true, subtree: true });

    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder för Avtal" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Ta bort" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Ta bort integrationskunskap" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));

    // Replaced, so Back does not lead to a page that is gone.
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/spaces/space-1/knowledge?tab=integrations")
    );
    observer.disconnect();
    expect(router.push).not.toHaveBeenCalled();
    expect(state.deleted).toHaveLength(1);
    // Nothing on its way out, not the "not found" state.
    expect(notFound).not.toContain(true);
    expect(screen.queryByRole("heading", { level: 1, name: "Avtal" })).toBeNull();
  });
});
