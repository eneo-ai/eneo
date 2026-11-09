// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { router } from "@/test/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import {
  spaceHasPermission,
  type ResourcePermission,
  type Space,
  type SpaceResource
} from "../space";
import {
  makeAssistant,
  makeCollection,
  makeIntegration,
  makeMember,
  makeSpace,
  makeWebsite
} from "../testing/space-fixture";

const state = vi.hoisted(() => ({
  space: null as unknown,
  progress: [] as unknown[],
  flows: [] as unknown[]
}));

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
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
    GET: (path: string) =>
      Promise.resolve({
        data: {
          items: path.endsWith("/sync-progress/")
            ? state.progress
            : path === "/api/v1/flows/"
              ? state.flows
              : []
        },
        response: new Response("{}")
      })
  }
}));
vi.mock("@/features/jobs/use-jobs", () => ({
  useJobs: () => ({ trackJob: () => {}, queueUploads: () => {} })
}));

import { SpaceOverview } from "@/features/spaces/overview/space-overview.client";

afterEach(() => {
  cleanup();
  state.progress = [];
  state.flows = [];
});

const contextOverrides: Parameters<typeof testAppContext>[0] = {
  permissions: ["admin"],
  settings: { using_templates: true },
  limits: {
    attachments: { formats: [] },
    info_blobs: {
      formats: [
        { mimetype: "application/pdf", extensions: ["pdf"], size: 10_000_000, vision: false }
      ]
    }
  }
};
const appContext = testAppContext(contextOverrides);
/** A tenant with flows switched on, for a user who may see them. */
const flowsAppContext = testAppContext({
  ...contextOverrides,
  featureFlags: { federation: false, flows: true }
});

function show(space: Space, { flows = false } = {}) {
  state.space = space;
  return renderInApp(<SpaceOverview />, { appContext: flows ? flowsAppContext : appContext });
}

const busySpace = () =>
  makeSpace({
    assistants: [makeAssistant(), makeAssistant({ id: "a2" }), makeAssistant({ id: "a3" })],
    groupChats: [{ id: "g1" }],
    apps: [{ id: "p1" }],
    collections: [makeCollection(), makeCollection({ id: "shared", space_id: "other" })],
    websites: [makeWebsite()],
    members: [makeMember(), makeMember({ id: "u2", email: "erik@example.com" })],
    overrides: { description: "Inköp och avtal." }
  });

const tiles = () =>
  within(screen.getByRole("list"))
    .getAllByRole("link")
    .map((link) => [link.getAttribute("aria-label"), link.getAttribute("href")]);

describe("SpaceOverview", () => {
  // Svelte's [spaceId]/overview/+page.svelte.
  it("titles the page Översikt and names the space under it, with its description", async () => {
    const { container } = show(busySpace());
    expect(screen.getByRole("heading", { level: 1, name: "Översikt" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "Upphandling" })).toBeTruthy();
    expect(screen.getByText("Inköp och avtal.")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("welcomes to a space without a description", () => {
    show(makeSpace({ overrides: { description: null } }));
    expect(screen.getByText("Välkommen till Upphandling")).toBeTruthy();
  });

  it("counts the space's own content in a tile per kind, each a link to its tab", () => {
    show(busySpace());
    expect(tiles()).toEqual([
      ["Assistenter 4", "/spaces/space-1/assistants"],
      ["Appar 1", "/spaces/space-1/apps"],
      // The collection shared in from another space is not this space's.
      ["Samlingar 1", "/spaces/space-1/knowledge?tab=collections"],
      ["Webbplatser 1", "/spaces/space-1/knowledge?tab=websites"],
      ["Medlemmar 2", "/spaces/space-1/members"]
    ]);
  });

  it("counts the flows too, after the apps, where the tenant has them", async () => {
    state.flows = [{ id: "f1" }, { id: "f2" }];
    show(busySpace(), { flows: true });
    // The flows are listed separately from the space, so their count arrives a moment later.
    await waitFor(() => expect(tiles()[2]).toEqual(["Flöden 2", "/spaces/space-1/flows"]));
    expect(tiles()).toHaveLength(6);
  });

  it("shows only the tiles the user may read", () => {
    show(makeSpace({ resourcePermissions: [], permissions: ["read"] }));
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("greets in the personal space, without the shared space's actions", () => {
    show(
      makeSpace({
        permissions: ["read"],
        overrides: { personal: true, members: { items: [], count: 0, permissions: [] } }
      })
    );
    expect(screen.getByRole("heading", { level: 2, name: /^Hej, / })).toBeTruthy();
    expect(screen.getByText(/din personliga yta/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Lägg till medlem" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Ny chatt" })).toBeNull();
  });

  it("starts a chat with the space's assistant, for those who may read it", () => {
    show(busySpace());
    expect(screen.getByRole("link", { name: "Ny chatt" }).getAttribute("href")).toBe(
      "/spaces/space-1/chat"
    );
    cleanup();
    show(makeSpace({ overrides: { default_assistant: null } }));
    expect(screen.queryByRole("link", { name: "Ny chatt" })).toBeNull();
  });

  it("opens the add-member dialog from the page bar and returns focus on Escape", async () => {
    show(busySpace());
    const invite = screen.getByRole("button", { name: "Lägg till medlem" });
    invite.focus();
    fireEvent.click(invite);

    const dialog = await screen.findByRole("dialog", { name: "Lägg till medlem" });
    expect(within(dialog).getByLabelText("E-post")).toBeTruthy();
    await expectNoAxeViolations(dialog);

    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(invite));
  });

  it("hides the add-member button without the permission", () => {
    show(makeSpace({ resourcePermissions: ["read"] }));
    expect(screen.queryByRole("button", { name: "Lägg till medlem" })).toBeNull();
  });
});

/**
 * A phone's create controls are small and secondary, like "Ladda upp": the
 * tabs' docked create buttons stay each screen's one primary action.
 */
function expectSecondaryCreate(scope: HTMLElement, name: string) {
  const create = within(scope).getByRole("button", { name });
  const more = within(scope).getByRole("button", { name: "Fler sätt att skapa" });
  expect([create.dataset.variant, create.dataset.size]).toEqual(["secondary", "sm"]);
  expect([more.dataset.variant, more.dataset.size]).toEqual(["secondary", "sm"]);
}

const app = (overrides: Record<string, unknown> = {}) => ({
  id: "app-1",
  name: "Protokoll från möte",
  description: "Gör ett protokoll av anteckningarna",
  published: true,
  permissions: ["read"],
  updated_at: "2026-09-10T08:00:00Z",
  ...overrides
});

const phoneSpace = (options: Parameters<typeof makeSpace>[0] = {}) =>
  makeSpace({
    assistants: [
      makeAssistant(),
      makeAssistant({ id: "a2", name: "Avtalsgranskaren", updated_at: "2026-09-05T08:00:00Z" }),
      makeAssistant({ id: "a3", name: "Äldst", updated_at: "2025-01-01T00:00:00Z" })
    ],
    apps: [
      app(),
      app({
        id: "app-2",
        name: "Anbudsutvärdering",
        published: false,
        updated_at: "2026-09-12T08:00:00Z"
      }),
      app({ id: "app-3", name: "Äldst", updated_at: "2025-01-01T00:00:00Z" })
    ],
    overrides: { description: "Inköp och avtal." },
    ...options
  });

describe("SpaceOverview on a phone", () => {
  // The tiles would repeat the phone's tabs (space-phone-header.tsx), which
  // also carry the space's name, description and Ny chatt.
  it("lists the newest assistants and apps instead of the count tiles", async () => {
    setViewport("phone");
    const { container } = show(phoneSpace());
    expect(screen.queryByRole("link", { name: /^Assistenter \d+$/ })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Upphandling" })).toBeNull();
    expect(screen.queryByText("Inköp och avtal.")).toBeNull();
    expect(screen.queryByRole("link", { name: "Ny chatt" })).toBeNull();

    const assistants = screen.getByRole("region", { name: "Assistenter" });
    const rows = within(within(assistants).getAllByRole("list")[0]!).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(within(rows[0]!).getByRole("link", { name: /^Avtalsgranskaren/ })).toBeTruthy();
    expectSecondaryCreate(
      within(assistants).getByRole("heading", { name: "Assistenter" }).parentElement!,
      "Skapa assistent"
    );
    expect(
      within(assistants).getByRole("link", { name: "Visa alla assistenter" }).getAttribute("href")
    ).toBe("/spaces/space-1/assistants");

    const apps = screen.getByRole("region", { name: "Appar" });
    const appRows = within(within(apps).getAllByRole("list")[0]!).getAllByRole("listitem");
    expect(appRows).toHaveLength(3);
    expect(within(appRows[0]!).getByRole("link", { name: /Anbudsutvärdering/ })).toBeTruthy();
    expect(within(appRows[0]!).getByText("Utkast")).toBeTruthy();
    expectSecondaryCreate(
      within(apps).getByRole("heading", { name: "Appar" }).parentElement!,
      "Skapa app"
    );
    // The actions menu belongs to the tabs.
    expect(within(apps).queryByRole("button", { name: /Fler åtgärder|Åtgärder/ })).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("invites to create the first assistant and app in an empty space", () => {
    setViewport("phone");
    show(makeSpace());
    const assistants = screen.getByRole("region", { name: "Assistenter" });
    expect(within(assistants).getByRole("heading", { name: "Inga assistenter ännu" })).toBeTruthy();
    // An empty section's one next step stays the filled button.
    expect(
      within(assistants).getByRole("button", { name: "Skapa assistent" }).dataset.variant
    ).toBe("primary");
    expect(within(assistants).queryByRole("link", { name: "Visa alla assistenter" })).toBeNull();
    expect(
      within(screen.getByRole("region", { name: "Appar" })).getByText("Inga appar ännu")
    ).toBeTruthy();
  });

  it("offers no create control to someone who may only read", () => {
    setViewport("phone");
    show(phoneSpace({ resourcePermissions: ["read"] }));
    expect(screen.queryByRole("button", { name: "Skapa assistent" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Skapa app" })).toBeNull();
  });

  it("leaves out apps for someone with none to open and none to create", () => {
    setViewport("phone");
    show(makeSpace({ resourcePermissions: ["read"] }));
    expect(screen.queryByRole("region", { name: "Appar" })).toBeNull();
  });
});

describe("SpaceOverview on a phone: Hantera ytan (decision 24)", () => {
  const manage = () => screen.getByRole("region", { name: "Hantera ytan" });
  const rows = () =>
    within(manage())
      .getAllByRole("link")
      .map((link) => [link.textContent, link.getAttribute("href")]);

  it("lists what manages the space, each opening its screen", async () => {
    setViewport("phone");
    const { container } = show(
      makeSpace({ members: [makeMember(), makeMember({ id: "u2", email: "erik@example.com" })] })
    );
    expect(rows()).toEqual([
      ["Medlemmar (2)", "/spaces/space-1/members"],
      ["Inställningar", "/spaces/space-1/settings"],
      ["Skills", "/spaces/space-1/skills"]
    ]);
    // After the space's content.
    const regions = screen
      .getAllByRole("region")
      .map((region) => region.getAttribute("aria-labelledby"));
    expect(regions.at(-1)).toBe(manage().getAttribute("aria-labelledby"));
    await expectNoAxeViolations(container);
  });

  it("lists only what the user may manage", () => {
    setViewport("phone");
    show(makeSpace({ permissions: ["read"], skillPermissions: [] }));
    expect(rows().map(([label]) => label)).toEqual(["Medlemmar (0)"]);
  });

  it("is not there on a tablet, which has a tab for each", () => {
    setViewport("tablet-portrait");
    show(makeSpace());
    expect(screen.queryByRole("region", { name: "Hantera ytan" })).toBeNull();
  });

  it("is not there for the organisation space, which keeps them as tabs (F4)", () => {
    setViewport("phone");
    show(makeSpace({ overrides: { organization: true } }));
    expect(screen.queryByRole("region", { name: "Hantera ytan" })).toBeNull();
  });
});

const listSpace = () =>
  makeSpace({
    assistants: [
      makeAssistant(),
      makeAssistant({
        id: "a2",
        name: "Avtalsgranskaren",
        published: false,
        completion_model_id: "model-2",
        updated_at: "2026-09-05T08:00:00Z"
      }),
      makeAssistant({ id: "a3", name: "Äldst", updated_at: "2025-01-01T00:00:00Z" })
    ],
    collections: [makeCollection()],
    websites: [
      makeWebsite({
        latest_crawl: {
          ...(makeWebsite().latest_crawl as Record<string, unknown>),
          status: "failed"
        }
      })
    ],
    members: [makeMember()]
  });

describe("SpaceOverview on a tablet: what to open (#1328)", () => {
  // Touch: the lists #1328 built, not the count tiles a mouse gets.
  beforeEach(() => setViewport("tablet-portrait"));

  it("leaves the title and the name to the space's header, and shows no count tiles", () => {
    show(listSpace());
    // SpaceHeader (space-frame.tsx) holds the space's h1 on a tablet.
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Upphandling" })).toBeNull();
    expect(screen.queryByRole("link", { name: /^Assistenter \d+$/ })).toBeNull();
  });

  it("shows the newest assistants and a compact knowledge list", async () => {
    const { container } = show(listSpace());

    const assistants = screen.getByRole("region", { name: "Assistenter" });
    expect(within(assistants).getByRole("link", { name: "Visa alla assistenter" })).toBeTruthy();
    // One row of the three newest; the create control sits in the heading, as on a
    // phone, so a dialog it opened stays open when the screen turns.
    const grid = within(assistants).getAllByRole("list")[0]!;
    const cards = Array.from(grid.children) as HTMLElement[];
    expect(cards).toHaveLength(3);
    expect(within(cards[0]!).getByRole("link", { name: "Avtalsgranskaren" })).toBeTruthy();
    expect(within(cards[0]!).getByText("Utkast")).toBeTruthy();
    expect(within(cards[0]!).getByText("claude-opus")).toBeTruthy();
    expect(within(cards[1]!).getByText("Publicerad")).toBeTruthy();
    expect(within(cards[1]!).getByText("Haiku 4.5")).toBeTruthy();
    expectSecondaryCreate(
      within(assistants).getByRole("heading", { name: "Assistenter" }).parentElement!,
      "Skapa assistent"
    );

    const knowledge = screen.getByRole("region", { name: "Kunskap" });
    // One column: knowledge follows the assistants.
    expect(knowledge.parentElement).toBe(assistants.parentElement);
    expect(within(knowledge).queryByRole("table")).toBeNull();
    expect(within(knowledge).getByText(/Samlingar, webbplatser och integrationer/)).toBeTruthy();
    const website = within(knowledge).getByRole("link", { name: "www.upphandlingsmyndigheten.se" });
    const websiteRow = website.closest("li")!;
    expect(within(websiteRow).getByText("Synkfel")).toBeTruthy();
    expect(within(websiteRow).getByText("318 sidor")).toBeTruthy();
    expect(
      within(websiteRow)
        .getByRole("link", { name: "Åtgärda www.upphandlingsmyndigheten.se" })
        .getAttribute("href")
    ).toBe("/spaces/space-1/knowledge/websites/website-1");
    const collectionRow = within(knowledge)
      .getByRole("link", { name: "Upphandlingspolicy" })
      .closest("li")!;
    expect(within(collectionRow).getByText("42 filer")).toBeTruthy();
    expect(within(collectionRow).getByText("Indexerad")).toBeTruthy();
    expect(
      within(collectionRow).getByRole("button", { name: "Fler åtgärder för Upphandlingspolicy" })
    ).toBeTruthy();
    expect(within(knowledge).getByRole("link", { name: "Visa alla kunskapskällor" })).toBeTruthy();

    await expectNoAxeViolations(container);
  });

  it("offers no second full sync of a source while one runs", async () => {
    state.progress = [
      {
        integration_knowledge_id: "integration-1",
        sync_type: "full",
        phase: "processing",
        started_at: "2026-10-19T08:00:00Z",
        updated_at: "2026-10-19T08:01:00Z",
        total: 12,
        done: 3,
        indexed: 3,
        unchanged: 0,
        skipped: 0,
        deleted: 0
      }
    ];
    show(makeSpace({ integrations: [makeIntegration()] }));
    const knowledge = screen.getByRole("region", { name: "Kunskap" });

    fireEvent.click(
      within(knowledge).getByRole("button", { name: "Fler åtgärder för Avtalsmallar" })
    );
    const busy = await screen.findByRole("menuitem", {
      name: "En synk är redan köad eller pågår"
    });
    expect(busy.getAttribute("aria-disabled")).toBe("true");
  });

  it("uploads to a chosen collection in the same dialog as the collection page", async () => {
    show(listSpace());

    const upload = screen.getByRole("button", { name: "Ladda upp" });
    fireEvent.click(upload);
    const item = await screen.findByRole("menuitem", { name: "Upphandlingspolicy" });
    await expectNoAxeViolations(document.body);
    fireEvent.click(item);

    // No detour to the collection page: the upload flow opens here, with the
    // accepted formats and limits.
    const dialog = await screen.findByRole("dialog", { name: "Ladda upp filer" });
    expect(within(dialog).getByText(/Upphandlingspolicy/)).toBeTruthy();
    expect(within(dialog).getByText(/pdf/i)).toBeTruthy();
    expect(router.push).not.toHaveBeenCalled();
  });

  it("shows empty states with the create actions in an empty space", async () => {
    const { container } = show(makeSpace());

    const assistants = screen.getByRole("region", { name: "Assistenter" });
    expect(within(assistants).getByRole("heading", { name: "Inga assistenter ännu" })).toBeTruthy();
    // An empty section's one next step stays the filled button.
    expect(
      within(assistants).getByRole("button", { name: "Skapa assistent" }).dataset.variant
    ).toBe("primary");
    expect(within(assistants).queryByRole("link", { name: "Visa alla assistenter" })).toBeNull();

    const knowledge = screen.getByRole("region", { name: "Kunskap" });
    expect(within(knowledge).getByRole("heading", { name: "Inga källor ännu" })).toBeTruthy();
    expect(within(knowledge).getByRole("button", { name: "Skapa samling" })).toBeTruthy();
    expect(within(knowledge).queryByRole("button", { name: "Ladda upp" })).toBeNull();

    await expectNoAxeViolations(container);
  });

  it("leaves out what the user may not see or change", () => {
    show(
      makeSpace({
        resourcePermissions: ["read"],
        assistants: [makeAssistant()],
        collections: [makeCollection({ permissions: ["read"] })],
        overrides: { organization: false }
      })
    );

    const assistants = screen.getByRole("region", { name: "Assistenter" });
    // No create card without create permission: three cards fit instead.
    expect(within(assistants).queryByRole("button", { name: "Skapa assistent" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Ladda upp" })).toBeNull();
  });

  it("hides assistants in the organization space", () => {
    show(makeSpace({ overrides: { organization: true } }));
    expect(screen.queryByRole("region", { name: "Assistenter" })).toBeNull();
    expect(screen.getByRole("region", { name: "Kunskap" })).toBeTruthy();
  });
});

const appSpace = (options: Parameters<typeof makeSpace>[0] = {}) =>
  makeSpace({
    apps: [
      app(),
      app({
        id: "app-2",
        name: "Anbudsutvärdering",
        published: false,
        updated_at: "2026-09-12T08:00:00Z"
      }),
      app({ id: "app-3", name: "Äldst", updated_at: "2025-01-01T00:00:00Z" })
    ],
    ...options
  });

describe("SpaceOverview on a tablet: apps", () => {
  beforeEach(() => setViewport("tablet-portrait"));

  it("shows the newest apps with the create button in the heading, and leads to the apps tab", () => {
    show(appSpace());
    const apps = screen.getByRole("region", { name: "Appar" });
    expect(within(apps).getByRole("link", { name: "Visa alla appar" }).getAttribute("href")).toBe(
      "/spaces/space-1/apps"
    );
    const cards = Array.from(within(apps).getAllByRole("list")[0]!.children) as HTMLElement[];
    expect(cards).toHaveLength(3);
    expect(within(cards[0]!).getByRole("link", { name: /Anbudsutvärdering/ })).toBeTruthy();
    expect(within(cards[0]!).getByText("Utkast")).toBeTruthy();
    expect(within(cards[1]!).getByRole("link", { name: /Protokoll från möte/ })).toBeTruthy();
    expectSecondaryCreate(
      within(apps).getByRole("heading", { name: "Appar" }).parentElement!,
      "Skapa app"
    );
    // The actions menu belongs to the apps tab.
    expect(within(apps).queryByRole("button", { name: /Fler åtgärder|Åtgärder/ })).toBeNull();
    // Assistants first, apps next, knowledge last: the order of the tabs.
    const order = screen
      .getAllByRole("heading", { level: 2 })
      .map((heading) => heading.textContent);
    expect(order.indexOf("Appar")).toBeGreaterThan(order.indexOf("Assistenter"));
    expect(order.indexOf("Appar")).toBeLessThan(order.indexOf("Kunskap"));
  });

  it("offers no create control to someone who may only read", () => {
    show(appSpace({ resourcePermissions: ["read"] }));
    const apps = screen.getByRole("region", { name: "Appar" });
    expect(within(apps).queryByRole("button", { name: "Skapa app" })).toBeNull();
    expect(within(apps).getAllByRole("link", { name: /^(?!Visa alla)/ }).length).toBe(3);
  });

  it("is not there for someone with no apps to open and none to create", () => {
    show(makeSpace({ resourcePermissions: ["read"] }));
    expect(screen.queryByRole("region", { name: "Appar" })).toBeNull();
  });

  it("invites someone who may create to make the first one", () => {
    show(makeSpace());
    const apps = screen.getByRole("region", { name: "Appar" });
    expect(within(apps).getByText("Inga appar ännu")).toBeTruthy();
    expect(within(apps).getByRole("button", { name: "Skapa app" })).toBeTruthy();
  });

  it("is not there for the organisation space", () => {
    show(appSpace({ overrides: { organization: true } }));
    expect(screen.queryByRole("region", { name: "Appar" })).toBeNull();
  });
});
