// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import {
  spaceHasPermission,
  type ResourcePermission,
  type Space,
  type SpaceResource
} from "@/features/spaces/space";
import {
  makeCollection,
  makeIntegration,
  makeSpace,
  makeWebsite
} from "@/features/spaces/testing/space-fixture";

const state = vi.hoisted(() => ({ space: null as unknown, tab: null as string | null }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: () => {}, prefetch: () => {} }),
  useSearchParams: () => new URLSearchParams(state.tab ? { tab: state.tab } : {})
}));
vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({
    space: state.space,
    routeId: "space-1",
    can: (action: ResourcePermission, resource: SpaceResource) =>
      spaceHasPermission(state.space as Space, action, resource)
  })
}));
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: () => Promise.resolve({ data: { items: [] }, response: new Response("{}") })
  }
}));
vi.mock("@/components/providers/app-context", () => ({
  useAppContext: () => ({ can: () => true, settings: {}, user: { id: "user-1" } })
}));
vi.mock("@/features/jobs/use-jobs", () => ({
  useJobs: () => ({ trackJob: () => {}, queueUploads: () => {} })
}));

import { KnowledgePage } from "./knowledge-page";

afterEach(cleanup);

function show(space: Space, tab: string | null = null) {
  state.space = space;
  state.tab = tab;
  return renderInApp(<KnowledgePage />);
}

describe("KnowledgePage", () => {
  it("keeps the Kunskap heading and tabs, with one create button in an empty space", async () => {
    const { container } = show(makeSpace());

    expect(screen.getByRole("heading", { level: 2, name: "Kunskap" })).toBeTruthy();
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Samlingar",
      "Webbplatser",
      "Integrationer"
    ]);
    expect(screen.getByRole("heading", { name: "Inga samlingar ännu" })).toBeTruthy();
    const create = screen.getAllByRole("button", { name: "Skapa samling" });
    expect(create).toHaveLength(1);
    await expectNoAxeViolations(container);

    fireEvent.click(create[0]!);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText(/Namn/)).toBeTruthy();
  });

  it("lists collections in a bordered table with status and a named row menu", async () => {
    const { container } = show(
      makeSpace({
        collections: [
          makeCollection(),
          makeCollection({
            id: "c2",
            name: "Tom samling",
            metadata: { num_info_blobs: 0, size: 0 }
          })
        ]
      })
    );

    const table = screen.getByRole("table");
    const policy = within(table).getByRole("link", { name: "Upphandlingspolicy" }).closest("tr")!;
    expect(within(policy).getByText("42 filer")).toBeTruthy();
    expect(within(policy).getByText("Indexerad")).toBeTruthy();
    const empty = within(table).getByRole("link", { name: "Tom samling" }).closest("tr")!;
    expect(within(empty).getByText("Tom")).toBeTruthy();
    expect(
      within(policy).getByRole("button", { name: "Fler åtgärder för Upphandlingspolicy" })
    ).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Filtrera samlingar" })).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("sorts collections by their column headers", () => {
    show(
      makeSpace({
        collections: [
          makeCollection({ id: "b", name: "Budget", metadata: { num_info_blobs: 3, size: 0 } }),
          makeCollection({ id: "a", name: "Ärenden", metadata: { num_info_blobs: 9, size: 0 } }),
          makeCollection({ id: "c", name: "Avtal", metadata: { num_info_blobs: 1, size: 0 } })
        ]
      })
    );
    const names = () =>
      within(screen.getByRole("table"))
        .getAllByRole("link")
        .map((link) => link.textContent);

    // Name, ascending, in Swedish order (Ä after Z).
    expect(names()).toEqual(["Avtal", "Budget", "Ärenden"]);
    expect(
      screen.getByRole("button", { name: "Sortera efter Namn, sorterat stigande" })
    ).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Sortera efter Innehåll" }));
    expect(names()).toEqual(["Avtal", "Budget", "Ärenden"]);
    fireEvent.click(
      screen.getByRole("button", { name: "Sortera efter Innehåll, sorterat stigande" })
    );
    expect(names()).toEqual(["Ärenden", "Budget", "Avtal"]);
  });

  it("shows website crawl states as status dots with text", async () => {
    const failed = makeWebsite({
      id: "w2",
      name: "Intranätet",
      latest_crawl: { ...(makeWebsite().latest_crawl as object), status: "failed" }
    });
    const { container } = show(
      makeSpace({ websites: [makeWebsite({ latest_crawl: null }), failed] }),
      "websites"
    );

    const table = screen.getByRole("table");
    // The same words as on the space overview.
    expect(within(table).getByText("Inte crawlad ännu")).toBeTruthy();
    expect(within(table).getByText("Synkfel")).toBeTruthy();
    expect(within(table).getAllByRole("link", { name: /Gå till webbplats/ })).toHaveLength(2);
    await expectNoAxeViolations(container);
  });

  it("selects websites for a bulk sync", () => {
    show(
      makeSpace({ websites: [makeWebsite(), makeWebsite({ id: "w2", name: "Intranätet" })] }),
      "websites"
    );
    expect(screen.getByRole("button", { name: "Anslut webbplats" })).toBeTruthy();

    fireEvent.click(screen.getByRole("checkbox", { name: "Markera Intranätet" }));
    expect(screen.getByRole("button", { name: "Synkronisera valda (1)" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Anslut webbplats" })).toBeNull();

    fireEvent.click(screen.getByRole("checkbox", { name: "Markera alla rader" }));
    expect(screen.getByRole("button", { name: "Synkronisera valda (2)" })).toBeTruthy();
  });

  it("lists integrations in a bordered table sorted by name, with folders and status dots", async () => {
    const { container } = show(
      makeSpace({
        integrations: [
          makeIntegration({ id: "i1", name: "Ärendehandbok", integration_type: "confluence" }),
          makeIntegration({
            id: "i2",
            name: "Avtalsmallar",
            metadata: { size: 0, last_synced_at: null, sharepoint_subscription_expires_at: null }
          }),
          makeIntegration({ id: "i3", name: "Mall 1", wrapper_id: "w1", wrapper_name: "Byggnad" }),
          makeIntegration({ id: "i4", name: "Mall 2", wrapper_id: "w1", wrapper_name: "Byggnad" })
        ]
      }),
      "integrations"
    );

    const table = await screen.findByRole("table");
    const names = () =>
      within(table)
        .getAllByRole("row")
        .slice(1)
        .map((row) => within(row).getAllByRole("cell")[0]!.textContent);
    // Name, ascending, in Swedish order (Ä after Z); the folder links to its page.
    expect(names()).toEqual(["Avtalsmallar", "Byggnad2 mappar", "Ärendehandbok"]);
    expect(within(table).getByRole("link", { name: "Byggnad" }).getAttribute("href")).toBe(
      "/spaces/space-1/knowledge/integrations/wrapper/w1"
    );
    const avtal = within(table).getByText("Avtalsmallar").closest("tr")!;
    expect(within(avtal).getByText("Ingen Webhook")).toBeTruthy();
    expect(
      within(avtal).getByRole("button", { name: /Ingen synk registrerad, Synkhistorik/ })
    ).toBeTruthy();
    expect(within(avtal).getByRole("link", { name: /Öppna i SharePoint/ })).toBeTruthy();
    expect(
      within(avtal).getByRole("button", { name: "Fler åtgärder för Avtalsmallar" })
    ).toBeTruthy();
    await expectNoAxeViolations(container);

    fireEvent.click(screen.getByRole("button", { name: "Sortera efter Status" }));
    expect(names()[0]).toBe("Avtalsmallar");
  });

  it("offers the next step for integrations in the empty state", () => {
    show(makeSpace(), "integrations");
    expect(screen.getByRole("heading", { name: "Inga integrationer ännu" })).toBeTruthy();
  });

  it("explains a missing create permission in text instead of a tooltip", () => {
    show(makeSpace({ resourcePermissions: ["read"] }));
    expect(screen.queryByRole("button", { name: "Skapa samling" })).toBeNull();
    expect(
      screen.getByText(/Du har inte behörighet att lägga till samlingar/, { selector: "span" })
    ).toBeTruthy();
  });
});
