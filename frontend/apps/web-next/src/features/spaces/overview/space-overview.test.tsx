// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { router } from "@/test/navigation";
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

const state = vi.hoisted(() => ({ space: null as unknown, progress: [] as unknown[] }));

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
        data: { items: path.endsWith("/sync-progress/") ? state.progress : [] },
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
});

const appContext = testAppContext({
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
});

function show(space: Space) {
  state.space = space;
  return renderInApp(<SpaceOverview />, { appContext });
}

/**
 * The overview's create controls are small and secondary, like "Ladda upp":
 * the tabs' docked create buttons stay each screen's one primary action.
 */
function expectSecondaryCreate(scope: HTMLElement, name: string) {
  const create = within(scope).getByRole("button", { name });
  const more = within(scope).getByRole("button", { name: "Fler sätt att skapa" });
  expect([create.dataset.variant, create.dataset.size]).toEqual(["secondary", "sm"]);
  expect([more.dataset.variant, more.dataset.size]).toEqual(["secondary", "sm"]);
}

const busySpace = () =>
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

describe("SpaceOverview", () => {
  it("leaves knowledge to the Kunskap tab on a phone, where the overview lists what to act on", () => {
    setViewport("phone");
    show(busySpace());
    expect(screen.getByRole("region", { name: "Assistenter" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Kunskap" })).toBeNull();
  });

  it("shows the newest assistants and a compact knowledge list", async () => {
    const { container } = show(busySpace());

    const assistants = screen.getByRole("region", { name: "Assistenter" });
    expect(within(assistants).getByRole("link", { name: "Visa alla assistenter" })).toBeTruthy();
    // One row: two newest cards plus the create card for users who may create.
    const grid = within(assistants).getAllByRole("list")[0]!;
    const cards = Array.from(grid.children) as HTMLElement[];
    expect(cards).toHaveLength(3);
    expect(within(cards[0]!).getByRole("link", { name: "Avtalsgranskaren" })).toBeTruthy();
    expect(within(cards[0]!).getByText("Utkast")).toBeTruthy();
    expect(within(cards[0]!).getByText("claude-opus")).toBeTruthy();
    expect(within(cards[1]!).getByText("Publicerad")).toBeTruthy();
    expect(within(cards[1]!).getByText("Haiku 4.5")).toBeTruthy();
    expect(within(cards[2]!).getByText("Börja från en mall eller från noll")).toBeTruthy();
    expectSecondaryCreate(cards[2]!, "Skapa assistent");
    expect(within(assistants).queryByRole("link", { name: "Äldst" })).toBeNull();

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
    show(busySpace());

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

  it("lists the newest assistants as rows, with the create button in the heading instead of a card", () => {
    setViewport("phone");
    show(busySpace());
    const assistants = screen.getByRole("region", { name: "Assistenter" });
    const rows = within(within(assistants).getAllByRole("list")[0]!).getAllByRole("listitem");
    // All three fit where the create card used to take the room of a row and a half.
    expect(rows).toHaveLength(3);
    expect(within(rows[0]!).getByRole("link", { name: /^Avtalsgranskaren/ })).toBeTruthy();
    const heading = within(assistants).getByRole("heading", { name: "Assistenter" }).parentElement!;
    expectSecondaryCreate(heading, "Skapa assistent");
    expect(within(assistants).queryByText("Börja från en mall eller från noll")).toBeNull();
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

const app = (overrides: Record<string, unknown> = {}) => ({
  id: "app-1",
  name: "Protokoll från möte",
  description: "Gör ett protokoll av anteckningarna",
  published: true,
  permissions: ["read"],
  updated_at: "2026-09-10T08:00:00Z",
  ...overrides
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

describe("SpaceOverview apps", () => {
  it("shows the newest apps, then the create card, and leads to the apps tab", () => {
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
    expectSecondaryCreate(cards[2]!, "Skapa app");
    expect(within(apps).queryByRole("link", { name: /Äldst/ })).toBeNull();
    // The actions menu belongs to the apps tab.
    expect(within(apps).queryByRole("button", { name: /Fler åtgärder|Åtgärder/ })).toBeNull();
    // Assistants first, apps next, knowledge last: the order of the tabs.
    const order = screen
      .getAllByRole("heading", { level: 2 })
      .map((heading) => heading.textContent);
    expect(order.indexOf("Appar")).toBeGreaterThan(order.indexOf("Assistenter"));
    expect(order.indexOf("Appar")).toBeLessThan(order.indexOf("Kunskap"));
  });

  it("puts the create button in the heading on a phone, and lists all three", () => {
    setViewport("phone");
    show(appSpace());
    const apps = screen.getByRole("region", { name: "Appar" });
    const rows = within(within(apps).getAllByRole("list")[0]!).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    const heading = within(apps).getByRole("heading", { name: "Appar" }).parentElement!;
    expectSecondaryCreate(heading, "Skapa app");
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
