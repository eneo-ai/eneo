// @vitest-environment jsdom
import { act, cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import {
  spaceHasPermission,
  type ResourcePermission,
  type Space,
  type SpaceResource
} from "../space";
import { makeMember, makeSpace } from "../testing/space-fixture";

const state = vi.hoisted(() => ({
  segments: [] as string[],
  space: null as unknown,
  routeId: "space-1"
}));

vi.mock("@/lib/navigation", () => ({
  useSpaceSegments: () => state.segments,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/spaces/space-1"
}));
vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({
    space: state.space,
    routeId: state.routeId,
    can: (action: ResourcePermission, resource: SpaceResource) =>
      spaceHasPermission(state.space as Space, action, resource)
  })
}));
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: vi.fn(() =>
      Promise.resolve({ data: { items: [] }, response: new Response("{}", { status: 200 }) })
    )
  }
}));

import { SpaceFrame } from "./space-frame";

afterEach(cleanup);

function show(space: Space, segments: string[], routeId = "space-1") {
  state.space = space;
  state.segments = segments;
  state.routeId = routeId;
  return renderInApp(
    <SpaceFrame>
      <p>Sidans innehåll</p>
    </SpaceFrame>
  );
}

const sharedSpace = () =>
  makeSpace({
    assistants: [{ id: "a1" }, { id: "a2" }],
    members: [
      makeMember(),
      makeMember({ id: "u2", email: "erik@example.com", role: "editor" }),
      makeMember({ id: "u3", email: "sara@example.com", role: "editor" }),
      makeMember({ id: "u4", email: "johan@example.com", role: "viewer" })
    ],
    overrides: {
      security_classification: { id: "sc", name: "Klass 2 · Intern", security_level: 2 }
    }
  });

describe("SpaceFrame", () => {
  it("renders the chat full-bleed, without the space header", () => {
    show(sharedSpace(), ["chat"]);
    expect(screen.getByText("Sidans innehåll")).toBeTruthy();
    expect(screen.queryByRole("banner")).toBeNull();
    expect(screen.queryByRole("navigation")).toBeNull();
  });

  it("renders an editor full-bleed, without the space header and tabs", () => {
    show(sharedSpace(), ["assistants", "a1", "edit"]);
    expect(screen.getByText("Sidans innehåll")).toBeTruthy();
    // The editor's own sticky header carries the breadcrumb back, so the space
    // header and tabs would only push its section tabs off the screen.
    expect(screen.queryByRole("banner")).toBeNull();
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.queryByRole("link", { name: "Ny chatt" })).toBeNull();
  });

  it("gives a page beside the sidebar no header of its own: the page's title is its h1", () => {
    const { container } = show(sharedSpace(), ["overview"]);
    // As in Svelte, the sidebar carries the space and its sections (SpaceNav).
    expect(screen.queryByRole("banner")).toBeNull();
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.queryByRole("heading")).toBeNull();
    expect(container.querySelector("[data-own-phone-header]")).toBeNull();
  });

  it("scrolls with the page panel instead of a scroll container of its own", () => {
    const { container } = show(sharedSpace(), ["overview"]);
    // main#main-content (the app shell) is the one scroll container, so Page
    // Down works after the skip link and nothing inside can trap the scroll.
    expect(container.querySelector(".overflow-y-auto, .overflow-auto")).toBeNull();
    const column = screen.getByText("Sidans innehåll").parentElement!;
    const inset = column.parentElement!;
    // The page inset, which a full-bleed page (the space settings) drops.
    expect(inset.className).toContain("p-6");
    expect(inset.className).toContain("has-[[data-space-full-bleed]]:p-0");
    // The pages' shared column, which a full-bleed page spans edge to edge.
    expect(column.className).toContain("max-w-6xl");
    expect(column.className).toContain("has-[[data-space-full-bleed]]:max-w-none");
  });
});

describe("SpaceFrame on a phone (decision 24)", () => {
  const phoneHeader = () => document.querySelector<HTMLElement>("[data-own-phone-header]");
  const tabHrefs = () =>
    within(screen.getByRole("navigation", { name: "Ytans innehåll" }))
      .getAllByRole("link")
      .map((link) => link.getAttribute("href"));

  it("pushes a shared space: back to Ytor, its name and class, the content tabs only", async () => {
    setViewport("phone");
    const { container } = show(sharedSpace(), ["overview"]);

    const back = screen.getByRole("link", { name: "Tillbaka till Ytor" });
    expect(back.getAttribute("href")).toBe("/spaces/list");
    expect(phoneHeader()?.contains(back)).toBe(true);
    expect(screen.getByRole("heading", { level: 1, name: "Upphandling" })).toBeTruthy();
    expect(screen.getByText("Säkerhetsklass:").parentElement?.textContent).toContain(
      "Klass 2 · Intern"
    );
    expect(tabHrefs()).toEqual([
      "/spaces/space-1/overview",
      "/spaces/space-1/assistants",
      "/spaces/space-1/apps",
      "/spaces/space-1/knowledge"
    ]);
    // The chat is one tap away in the bar; the breadcrumbs and the member stack are not here.
    expect(
      within(phoneHeader()!).getByRole("link", { name: "Ny chatt" }).getAttribute("href")
    ).toBe("/spaces/space-1/chat");
    expect(screen.queryByRole("navigation", { name: /brödsmulor|breadcrumb/i })).toBeNull();
    expect(screen.queryByRole("group", { name: /medlemmar/ })).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("keeps the menu for the personal space, which the menu leads to", () => {
    setViewport("phone");
    show(
      makeSpace({
        overrides: { personal: true, members: { items: [], count: 0, permissions: [] } },
        permissions: ["read"]
      }),
      ["assistants"],
      "personal"
    );
    expect(screen.queryByRole("link", { name: /^Tillbaka till/ })).toBeNull();
    expect(phoneHeader()).toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: "Personligt" })).toBeTruthy();
    expect(tabHrefs()).toEqual([
      "/spaces/personal/overview",
      "/spaces/personal/assistants",
      "/spaces/personal/apps",
      "/spaces/personal/knowledge"
    ]);
  });

  it("keeps every tab of the organisation space, which has no Översikt (F4)", () => {
    setViewport("phone");
    show(makeSpace({ overrides: { organization: true } }), ["knowledge"], "organization");
    expect(phoneHeader()).toBeNull();
    expect(tabHrefs()).toEqual([
      "/spaces/organization/knowledge",
      "/spaces/organization/skills",
      "/spaces/organization/settings"
    ]);
  });

  it("pushes Medlemmar from the space: back to the space, no tabs", () => {
    setViewport("phone");
    show(sharedSpace(), ["members"]);
    const back = screen.getByRole("link", { name: "Tillbaka till Upphandling" });
    expect(back.getAttribute("href")).toBe("/spaces/space-1/overview");
    expect(screen.queryByRole("navigation", { name: "Ytans innehåll" })).toBeNull();
    // The page's own heading follows the space's.
    expect(screen.getByRole("heading", { level: 1, name: "Upphandling" })).toBeTruthy();
  });

  it("pushes a page below a tab: back to the tab, its own heading", () => {
    setViewport("phone");
    show(sharedSpace(), ["knowledge", "collections", "c1"]);
    const back = screen.getByRole("link", { name: "Tillbaka till Kunskap" });
    expect(back.getAttribute("href")).toBe("/spaces/space-1/knowledge");
    expect(screen.queryByRole("navigation", { name: "Ytans innehåll" })).toBeNull();
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
  });

  it("gives a section root outside the tabs its h1, and keeps the menu for the organisation space", () => {
    setViewport("phone");
    // /spaces/organization redirects here, though the organisation space has no Översikt.
    show(makeSpace({ overrides: { organization: true } }), ["overview"], "organization");
    expect(screen.getAllByRole("heading", { level: 1 }).map((h) => h.textContent)).toEqual([
      "Organisation"
    ]);
    expect(phoneHeader()).toBeNull();
  });

  it("goes back from an app's result to the app, the screen it was opened from", () => {
    setViewport("phone");
    show(makeSpace({ apps: [{ id: "p1", name: "Bygglovsguiden" }] }), [
      "apps",
      "p1",
      "results",
      "r1"
    ]);
    expect(
      screen.getByRole("link", { name: "Tillbaka till Bygglovsguiden" }).getAttribute("href")
    ).toBe("/spaces/space-1/apps/p1");
  });

  it("is not on a tablet, which has the sidebar", () => {
    setViewport("tablet-portrait");
    show(sharedSpace(), ["overview"]);
    expect(phoneHeader()).toBeNull();
    expect(screen.queryByRole("navigation")).toBeNull();
  });

  it("is on a phone turned sideways, which has no height for the breadcrumb and seven tabs", () => {
    setViewport("phone-landscape");
    show(sharedSpace(), ["overview"]);
    expect(phoneHeader()).not.toBeNull();
    expect(tabHrefs()).toHaveLength(4);
    expect(screen.queryByRole("navigation", { name: /brödsmulor|breadcrumb/i })).toBeNull();
  });

  it("turns with the phone: its header comes when it is laid sideways, and goes again", () => {
    setViewport("tablet-portrait");
    show(sharedSpace(), ["overview"]);
    act(() => setViewport("phone-landscape"));
    expect(phoneHeader()).not.toBeNull();
    expect(tabHrefs()).toHaveLength(4);
    // An iPad turned with its keyboard up is short too, but as wide as a laptop: the tablet's.
    act(() => setViewport({ width: 1180, height: 470, pointer: "coarse" }));
    expect(phoneHeader()).toBeNull();
    expect(screen.queryByRole("navigation")).toBeNull();
  });
});
