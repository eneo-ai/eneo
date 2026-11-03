// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
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
