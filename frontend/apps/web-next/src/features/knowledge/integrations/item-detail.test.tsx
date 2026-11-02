// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { router, setRoute } from "@/test/navigation";
import { renderInApp, testQueryClient } from "@/test/render";
import type { Space } from "@/features/spaces/space";

const state = vi.hoisted(() => ({ space: null as unknown, deleted: [] as string[] }));

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
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
      POST: (
        _path: string,
        options: {
          body: { items: { integration_knowledge_id: string; offset: number }[]; limit: number };
        }
      ) =>
        ok({
          items: options.body.items.map((item) => ({
            integration_knowledge_id: item.integration_knowledge_id,
            history: { items: [], total_count: 0, offset: item.offset, limit: options.body.limit },
            skipped: { items: [], total: 0, truncated: false, synced_at: null }
          }))
        }),
      DELETE: (path: string) => {
        state.deleted.push(path);
        // What the space holds once the item is gone.
        state.space = makeSpace();
        return ok(null, 204);
      }
    }
  };
});

import { IntegrationActions } from "@/features/knowledge/integrations/actions";
import { resetPendingSyncs } from "@/features/knowledge/integrations/pending-syncs";
import type { LoadedItems } from "@/features/knowledge/integrations/use-source-items";
import type { IntegrationKnowledge } from "@/features/knowledge/knowledge";
import { makeIntegration, makeSpace } from "@/features/spaces/testing/space-fixture";
import { ItemDetail } from "@/features/knowledge/integrations/item-detail.client";

afterEach(() => {
  cleanup();
  state.deleted = [];
  resetPendingSyncs();
});

function avtal(fields: Record<string, unknown> = {}) {
  return makeIntegration({
    id: "i1",
    name: "Avtal",
    selected_item_type: "file",
    permissions: ["read", "edit", "delete"],
    metadata: { size: 0, last_synced_at: "2026-10-14T08:00:00Z", document_count: 1 },
    ...fields
  });
}

/** The item as the server page found it. */
function served(fields: Record<string, unknown> = {}): LoadedItems {
  return { items: [avtal(fields) as IntegrationKnowledge] };
}

function show(fields: Record<string, unknown> = {}) {
  state.space = makeSpace({ integrations: [avtal(fields)] });
  setRoute("/spaces/space-1/knowledge/integrations/i1");
  return renderInApp(<ItemDetail itemId="i1" loaded={served(fields)} />);
}

async function deleteFromMenu() {
  fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder för Avtal" }));
  fireEvent.click(await screen.findByRole("menuitem", { name: "Ta bort" }));
  const dialog = await screen.findByRole("alertdialog", { name: "Ta bort integrationskunskap" });
  fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));
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
    const atSource = screen.getByRole("link", { name: /Öppna i SharePoint/ });
    expect(atSource.getAttribute("href")).toBe("https://kommun.sharepoint.com/sites/avtal");
    // A new tab that cannot reach back into Eneo, and is not told where it came from.
    expect(atSource.getAttribute("target")).toBe("_blank");
    expect(atSource.getAttribute("rel")).toBe("noopener noreferrer");
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

    await deleteFromMenu();

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

  it("says the item is gone when Back leads to its page after a delete from the list", async () => {
    // The list's row menu deletes it ...
    state.space = makeSpace({ integrations: [avtal()] });
    setRoute("/spaces/space-1/knowledge?tab=integrations");
    const list = renderInApp(<IntegrationActions item={avtal() as IntegrationKnowledge} />);
    await deleteFromMenu();
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(state.deleted).toHaveLength(1);
    list.unmount();

    // ... and Back shows its page again, from the router's cache: as the server
    // found it before the delete.
    setRoute("/spaces/space-1/knowledge/integrations/i1");
    renderInApp(<ItemDetail itemId="i1" loaded={served()} />, {
      queryClient: list.queryClient
    });

    expect(
      await screen.findByRole("heading", { level: 1, name: "Inga resultat hittades" })
    ).toBeTruthy();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("says the item is gone on a later visit to the page it was deleted from", async () => {
    const page = show();
    await deleteFromMenu();
    await waitFor(() => expect(router.replace).toHaveBeenCalledTimes(1));
    page.unmount();

    setRoute("/spaces/space-1/knowledge/integrations/i1");
    renderInApp(<ItemDetail itemId="i1" loaded={served()} />, {
      queryClient: page.queryClient
    });

    expect(
      await screen.findByRole("heading", { level: 1, name: "Inga resultat hittades" })
    ).toBeTruthy();
  });

  it("shows an item imported since the space was cached, as the server page found it", async () => {
    // The browser's space is from before the import, and still fresh enough not to be read again.
    const queryClient = testQueryClient();
    queryClient.setQueryData(["spaces", "space-1"], makeSpace(), { updatedAt: Date.now() - 5_000 });
    state.space = makeSpace({ integrations: [avtal()] });
    setRoute("/spaces/space-1/knowledge/integrations/i1");
    const notFound: boolean[] = [];
    const observer = new MutationObserver(() =>
      notFound.push(screen.queryByText("Inga resultat hittades") !== null)
    );
    observer.observe(document.body, { childList: true, subtree: true });

    renderInApp(<ItemDetail itemId="i1" loaded={served()} />, { queryClient });

    expect(screen.getByRole("heading", { level: 1, name: "Avtal" })).toBeTruthy();
    // The page reads the space again, which now holds the item.
    await waitFor(() =>
      expect(
        queryClient.getQueryData<Space>(["spaces", "space-1"])?.knowledge.integration_knowledge_list
          .items
      ).toHaveLength(1)
    );
    observer.disconnect();
    expect(notFound).not.toContain(true);
    expect(screen.getByRole("heading", { level: 1, name: "Avtal" })).toBeTruthy();
  });

  it("does not bring the server's copy back once the space has shown the item", async () => {
    state.space = makeSpace({ integrations: [avtal()] });
    setRoute("/spaces/space-1/knowledge/integrations/i1");
    const { queryClient } = renderInApp(<ItemDetail itemId="i1" loaded={served()} />);
    expect(screen.getByRole("heading", { level: 1, name: "Avtal" })).toBeTruthy();

    // Deleted in another tab.
    state.space = makeSpace();
    await act(() => queryClient.invalidateQueries({ queryKey: ["spaces", "space-1"] }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Inga resultat hittades" })
    ).toBeTruthy();
    expect(router.replace).not.toHaveBeenCalled();
  });
});
