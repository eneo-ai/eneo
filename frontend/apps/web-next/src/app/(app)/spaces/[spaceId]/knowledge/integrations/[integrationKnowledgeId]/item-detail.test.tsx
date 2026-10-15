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

function show() {
  state.space = makeSpace({
    integrations: [
      makeIntegration({
        id: "i1",
        name: "Avtal",
        selected_item_type: "file",
        permissions: ["read", "edit", "delete"],
        metadata: { size: 0, last_synced_at: "2026-10-14T08:00:00Z", document_count: 1 }
      })
    ]
  });
  setRoute("/spaces/space-1/knowledge/integrations/i1");
  return renderInApp(<ItemDetail itemId="i1" />);
}

describe("ItemDetail", () => {
  it("shows the item as its own source, with the vendor's logo as decoration", async () => {
    const { container } = show();

    expect(screen.getByRole("heading", { level: 1, name: "Avtal" })).toBeTruthy();
    // The logo sits next to the visible "1 fil"; its vendor name is not read out on its own.
    expect(container.querySelector("img")?.getAttribute("alt")).toBe("");
    await expectNoAxeViolations(container);
  });

  it("goes back to the list once the item was deleted from its own page", async () => {
    show();

    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder för Avtal" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Ta bort" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Ta bort integrationskunskap" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));

    await waitFor(() =>
      expect(router.push).toHaveBeenCalledWith("/spaces/space-1/knowledge?tab=integrations")
    );
    expect(state.deleted).toHaveLength(1);
  });
});
