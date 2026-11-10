// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
import { browserApi } from "@/lib/api/browser";
import { flowQueryOptions, type FlowPublic } from "@/features/flows/flows-api";
import { setViewport } from "@/test/setup-dom";
import { PageHeader } from "@/components/composites/page-header";
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

// A tablet's header is a chunk of its own: one render loads it, so every test then renders it at once.
let h1WhileLoading: string | null | undefined;
beforeAll(async () => {
  // Fetched first: on a loaded test machine the chunk outlasts findBy's wait.
  await import("./space-header");
  setViewport("tablet-portrait");
  show(sharedSpace(), ["overview"]);
  h1WhileLoading = document.querySelector('[aria-busy="true"] h1')?.textContent;
  await screen.findByRole("button", { name: "Lägg till medlem" });
  cleanup();
  setViewport("desktop");
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

  it("names the space above a section page for when the sidebar is its icon rail", () => {
    // A small laptop: a mouse, under 1280 px.
    setViewport({ width: 1024, height: 768, pointer: "fine" });
    show(sharedSpace(), ["assistants"]);
    // Shown by CSS only while the shell marks the rail (app-shell.tsx data-side-nav-rail).
    const eyebrow = document.querySelector<HTMLElement>("[data-space-eyebrow]")!;
    expect(eyebrow.textContent).toContain("Upphandling");
    expect(eyebrow.textContent).toContain("Klass 2 · Intern");
    expect(eyebrow.className).toMatch(/group-has-\[\[data-side-nav-rail\]\]\/shell:flex/);
    expect(eyebrow.className).toMatch(/(^| )hidden( |$)/);
    setViewport("desktop");
  });

  it("names it nowhere else: Översikt shows the name, a phone and a tablet have their header", () => {
    show(sharedSpace(), ["overview"]);
    expect(document.querySelector("[data-space-eyebrow]")).toBeNull();
    cleanup();
    for (const viewport of ["phone", "tablet-portrait"] as const) {
      cleanup();
      setViewport(viewport);
      show(sharedSpace(), ["assistants"]);
      expect(document.querySelector("[data-space-eyebrow]")).toBeNull();
    }
    setViewport("desktop");
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

describe("SpaceFrame on a tablet: the space's header and tabs (#1328)", () => {
  // Touch: the SideNav lists every space, so the page names its own.
  beforeEach(() => setViewport("tablet-portrait"));
  afterEach(() => setViewport("desktop"));

  it("is busy until the header's chunk lands, with the space name as the h1", () => {
    expect(h1WhileLoading).toBe("Upphandling");
  });

  it("gives a tab page the space name as its h1, breadcrumbs, members and tabs", async () => {
    const { container } = show(sharedSpace(), ["overview"]);

    expect(screen.getByRole("heading", { level: 1, name: "Upphandling" })).toBeTruthy();
    expect(screen.getByText("Stöd för kommunens upphandlare.")).toBeTruthy();
    // ClassificationToken: read with its prefix.
    expect(screen.getByText("Klass 2 · Intern").parentElement!.textContent).toBe(
      "Säkerhetsklass: Klass 2 · Intern"
    );

    const crumbs = screen.getAllByRole("navigation")[0]!;
    expect(within(crumbs).getByRole("link", { name: "Dina ytor" }).getAttribute("href")).toBe(
      "/spaces/list"
    );
    expect(within(crumbs).getByText("Upphandling").closest("[aria-current='page']")).toBeTruthy();

    const tabs = screen.getByRole("navigation", { name: "Ytans innehåll" });
    const links = within(tabs).getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/spaces/space-1/overview",
      "/spaces/space-1/assistants",
      "/spaces/space-1/apps",
      "/spaces/space-1/knowledge",
      "/spaces/space-1/skills",
      "/spaces/space-1/members",
      "/spaces/space-1/settings"
    ]);
    expect(within(tabs).getByRole("link", { name: "Översikt" }).getAttribute("aria-current")).toBe(
      "true"
    );
    // Named by what it shows, the count with it, so the name holds the visible label (WCAG 2.5.3).
    const assistants = within(tabs).getByRole("link", { name: "Assistenter 2" });
    expect(assistants.hasAttribute("aria-label")).toBe(false);
    expect(within(tabs).getByRole("link", { name: "Skills" })).toBeTruthy();

    expect(screen.getByRole("group", { name: "4 medlemmar" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Lägg till medlem" })).toBeTruthy();
    const newChat = screen.getByRole("link", { name: "Ny chatt" });
    expect(newChat.getAttribute("href")).toBe("/spaces/space-1/chat");
    // Each tab's own create button is the one primary action; a new chat stays in reach.
    expect(newChat.getAttribute("data-variant")).toBe("secondary");
    expect(screen.getByText("Sidans innehåll")).toBeTruthy();

    await expectNoAxeViolations(container);
  });

  it("centres the name on the tile when no description runs under it", () => {
    const column = () =>
      screen.getByRole("heading", { level: 1, name: "Upphandling" }).closest(".flex-col")!;
    show(sharedSpace(), ["overview"]);
    // A description under the name: both start at the tile's top edge.
    expect(column().className).not.toContain("self-center");
    cleanup();
    show(makeSpace({ overrides: { description: null } }), ["overview"]);
    expect(column().className).toContain("self-center");
  });

  it("lines the header up with the page below it, in the pages' shared column", () => {
    show(sharedSpace(), ["overview"]);
    const header = screen
      .getByRole("heading", { level: 1, name: "Upphandling" })
      .closest("header")!;
    // The band and its border span the frame; the name, actions and tabs start on the page's line.
    expect(header.className).toContain("border-b");
    expect(header.className).not.toContain("max-w-6xl");
    expect(header.firstElementChild!.className).toContain("max-w-6xl");
    expect(header.firstElementChild!.className).toContain("mx-auto");
  });

  it("leaves the h1 to a detail page and marks its tab as current", async () => {
    const { container } = show(sharedSpace(), ["knowledge", "collections", "c1"]);

    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
    // The space name is a small label there, not a second title.
    expect(screen.getByText("Upphandling", { selector: "p" }).className).toContain("text-sm");
    // The description belongs to the tab pages; details keep the header short.
    expect(screen.queryByText("Stöd för kommunens upphandlare.")).toBeNull();
    const crumbs = screen.getAllByRole("navigation")[0]!;
    expect(within(crumbs).getByRole("link", { name: "Upphandling" }).getAttribute("href")).toBe(
      "/spaces/space-1/overview"
    );
    const tabs = screen.getByRole("navigation", { name: "Ytans innehåll" });
    expect(within(tabs).getByRole("link", { name: "Kunskap 0" }).getAttribute("aria-current")).toBe(
      "true"
    );

    await expectNoAxeViolations(container);
  });

  it("names its trail apart from the trail a page below a tab brings (a flow run's)", () => {
    state.space = sharedSpace();
    state.segments = ["flows", "f1", "runs", "r1"];
    renderInApp(
      <SpaceFrame>
        <PageHeader
          title="Körning 3"
          breadcrumbs={[
            { label: "Upphandling", href: "/spaces/space-1/overview" },
            { label: "Flöden", href: "/spaces/space-1/flows" },
            { label: "Körning 3", current: true }
          ]}
        />
      </SpaceFrame>
    );

    const names = screen.getAllByRole("navigation").map((nav) => nav.getAttribute("aria-label"));
    expect(names).toEqual(["Ytans sökväg", "Ytans innehåll", "Sökväg"]);
  });

  it("leaves the space's name out above a page whose own trail starts with it (a flow run)", () => {
    show(sharedSpace(), ["flows", "f1", "runs", "r1"]);
    // The run page's trail begins "Upphandling › Flöden": no small label repeats it.
    expect(screen.queryByText("Upphandling", { selector: "p" })).toBeNull();
    // Another page below a tab still names the space.
    cleanup();
    show(sharedSpace(), ["knowledge", "collections", "c1"]);
    expect(screen.getByText("Upphandling", { selector: "p" })).toBeTruthy();
  });

  it("shows the personal space without members or invites", () => {
    const space = makeSpace({
      permissions: ["read"],
      overrides: { personal: true, members: { items: [], count: 0, permissions: [] } }
    });
    show(space, ["overview"], "personal");

    expect(screen.getByRole("heading", { level: 1, name: "Personligt" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Lägg till medlem" })).toBeNull();
    expect(screen.queryByRole("group", { name: /medlem/ })).toBeNull();
    const newChat = screen.getByRole("link", { name: "Ny chatt" });
    expect(newChat.getAttribute("href")).toBe("/spaces/personal/chat");
    expect(newChat.getAttribute("data-variant")).toBe("secondary");
    const tabs = screen.getByRole("navigation", { name: "Ytans innehåll" });
    expect(within(tabs).queryByRole("link", { name: /Medlemmar/ })).toBeNull();
    expect(within(tabs).queryByRole("link", { name: "Inställningar" })).toBeNull();
  });

  it("keeps the organization space to its three tabs, named by the h1 on its Skills tab", () => {
    show(makeSpace({ overrides: { organization: true } }), ["skills"], "organization");

    // The Skills page is a tab like any other: its own title is an h2.
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.queryByRole("link", { name: "Ny chatt" })).toBeNull();
    const tabs = screen.getByRole("navigation", { name: "Ytans innehåll" });
    expect(
      within(tabs)
        .getAllByRole("link")
        .map((link) => link.getAttribute("href"))
    ).toEqual([
      "/spaces/organization/knowledge",
      "/spaces/organization/skills",
      "/spaces/organization/settings"
    ]);
    expect(within(tabs).getByRole("link", { name: "Skills" }).getAttribute("aria-current")).toBe(
      "true"
    );
  });

  it("hides actions the user lacks permission for", () => {
    const space = makeSpace({
      resourcePermissions: ["read"],
      permissions: ["read"],
      members: [makeMember()],
      overrides: { default_assistant: null }
    });
    show(space, ["overview"]);

    expect(screen.queryByRole("button", { name: "Lägg till medlem" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Ny chatt" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Inställningar" })).toBeNull();
    expect(screen.getByRole("group", { name: "1 medlem" })).toBeTruthy();
  });

  it("keeps the tabs one tab stop that arrow keys move through", () => {
    show(sharedSpace(), ["knowledge"]);
    const tabs = screen.getByRole("navigation", { name: "Ytans innehåll" });
    const current = within(tabs).getByRole("link", { name: "Kunskap 0" });
    const others = within(tabs)
      .getAllByRole("link")
      .filter((link) => link !== current);

    expect(current.getAttribute("tabindex")).toBe("0");
    expect(others.every((link) => link.getAttribute("tabindex") === "-1")).toBe(true);

    current.focus();
    fireEvent.keyDown(current, { key: "ArrowRight" });
    expect(document.activeElement).toBe(within(tabs).getByRole("link", { name: "Skills" }));
  });

  it("leaves adding members to the members tab's own button there", () => {
    show(sharedSpace(), ["members"]);
    expect(screen.queryByRole("button", { name: "Lägg till medlem" })).toBeNull();
  });

  it("opens the add-member dialog from the header and returns focus on Escape", async () => {
    show(sharedSpace(), ["overview"]);
    const invite = screen.getByRole("button", { name: "Lägg till medlem" });
    invite.focus();
    fireEvent.click(invite);

    const dialog = await screen.findByRole("dialog", { name: "Lägg till medlem" });
    expect(within(dialog).getByLabelText("E-post")).toBeTruthy();
    expect(within(dialog).getByRole("combobox", { name: "Roll" })).toBeTruthy();
    // The dialog itself: while a Radix modal is open, Radix leaves every
    // [aria-live] subtree (each Astryx Button has one) outside aria-hidden,
    // which is a shell-wide issue tracked in the migration report.
    await expectNoAxeViolations(dialog);

    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(invite));
  });
});

describe("SpaceFrame on a phone (decision 24)", () => {
  const phoneHeader = () => document.querySelector<HTMLElement>("[data-own-phone-header]");
  const tabHrefs = () =>
    within(screen.getByRole("navigation", { name: "Ytans innehåll" }))
      .getAllByRole("link")
      .map((link) => link.getAttribute("href"));

  it("pushes a shared space: back to Dina ytor, its name and class, the content tabs only", async () => {
    setViewport("phone");
    const { container } = show(sharedSpace(), ["overview"]);

    const back = screen.getByRole("link", { name: "Tillbaka till Dina ytor" });
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

  it("adds Flöden to the tabs where the tenant has flows, and not where it has none", () => {
    setViewport("phone");
    state.space = sharedSpace();
    state.segments = ["overview"];
    state.routeId = "space-1";
    renderInApp(
      <SpaceFrame>
        <p>Sidans innehåll</p>
      </SpaceFrame>,
      { appContext: testAppContext({ featureFlags: { federation: false, flows: true } }) }
    );
    expect(tabHrefs()).toEqual([
      "/spaces/space-1/overview",
      "/spaces/space-1/assistants",
      "/spaces/space-1/apps",
      "/spaces/space-1/flows",
      "/spaces/space-1/knowledge"
    ]);
    cleanup();
    show(sharedSpace(), ["overview"]);
    expect(tabHrefs()).not.toContain("/spaces/space-1/flows");
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

  it("goes back from a flow's run to that flow's runs, named by the flow", () => {
    setViewport("phone");
    state.space = sharedSpace();
    state.segments = ["flows", "f1", "runs", "r1"];
    state.routeId = "space-1";
    const queryClient = testQueryClient();
    queryClient.setQueryData(flowQueryOptions(browserApi, "f1").queryKey, {
      id: "f1",
      name: "Protokoll från nämnden"
    } as FlowPublic);
    renderInApp(
      <SpaceFrame>
        <p>Sidans innehåll</p>
      </SpaceFrame>,
      {
        queryClient,
        appContext: testAppContext({ featureFlags: { federation: false, flows: true } })
      }
    );
    expect(
      screen
        .getByRole("link", { name: "Tillbaka till Protokoll från nämnden" })
        .getAttribute("href")
    ).toBe("/spaces/space-1/flows/f1?tab=runs");
  });

  it("is not on a tablet, which keeps the header with every tab", () => {
    setViewport("tablet-portrait");
    show(sharedSpace(), ["overview"]);
    expect(phoneHeader()).toBeNull();
    expect(tabHrefs()).toHaveLength(7);
  });

  it("is on a phone turned sideways, which has no height for the breadcrumb and seven tabs", () => {
    setViewport("phone-landscape");
    show(sharedSpace(), ["overview"]);
    expect(phoneHeader()).not.toBeNull();
    expect(tabHrefs()).toHaveLength(4);
    expect(screen.queryByRole("navigation", { name: /brödsmulor|breadcrumb/i })).toBeNull();
  });

  it("turns with the phone: the header swaps for the phone's when it is laid sideways", () => {
    setViewport("tablet-portrait");
    show(sharedSpace(), ["overview"]);
    act(() => setViewport("phone-landscape"));
    expect(phoneHeader()).not.toBeNull();
    expect(tabHrefs()).toHaveLength(4);
    // An iPad turned with its keyboard up is short too, but as wide as a laptop: the tablet's.
    act(() => setViewport({ width: 1180, height: 470, pointer: "coarse" }));
    expect(phoneHeader()).toBeNull();
    expect(tabHrefs()).toHaveLength(7);
  });
});
