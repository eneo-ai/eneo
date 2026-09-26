// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
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

vi.mock("next/navigation", () => ({
  useSelectedLayoutSegments: () => state.segments,
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

  it("gives a tab page the space name as its h1, breadcrumbs, members and tabs", async () => {
    const { container } = show(sharedSpace(), ["overview"]);

    expect(screen.getByRole("heading", { level: 1, name: "Upphandling" })).toBeTruthy();
    expect(screen.getByText("Stöd för kommunens upphandlare.")).toBeTruthy();
    expect(screen.getByText("Klass 2 · Intern").textContent).toBe(
      "Säkerhetsklass: Klass 2 · Intern"
    );

    const crumbs = screen.getAllByRole("navigation")[0]!;
    expect(within(crumbs).getByRole("link", { name: "Ytor" }).getAttribute("href")).toBe(
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
      "/spaces/space-1/services",
      "/spaces/space-1/members",
      "/spaces/space-1/settings"
    ]);
    expect(within(tabs).getByRole("link", { name: "Översikt" }).getAttribute("aria-current")).toBe(
      "true"
    );
    expect(within(tabs).getByRole("link", { name: "Assistenter (2)" })).toBeTruthy();
    expect(within(tabs).getByRole("link", { name: "Skills" })).toBeTruthy();

    expect(screen.getByRole("group", { name: "4 medlemmar" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Lägg till medlem" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Ny chatt" }).getAttribute("href")).toBe(
      "/spaces/space-1/chat"
    );
    expect(screen.getByText("Sidans innehåll")).toBeTruthy();

    await expectNoAxeViolations(container);
  });

  it("scrolls with the page panel instead of a scroll container of its own", () => {
    const { container } = show(sharedSpace(), ["overview"]);
    // main#main-content (the app shell) is the one scroll container, so Page
    // Down works after the skip link and nothing inside can trap the scroll.
    expect(container.querySelector(".overflow-y-auto, .overflow-auto")).toBeNull();
    const content = screen.getByText("Sidans innehåll").parentElement!;
    // The page inset, which a full-bleed page (the assistant editor) drops.
    expect(content.className).toContain("p-6");
    expect(content.className).toContain("has-[[data-space-full-bleed]]:p-0");
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
    expect(
      within(tabs).getByRole("link", { name: "Kunskap (0)" }).getAttribute("aria-current")
    ).toBe("true");

    await expectNoAxeViolations(container);
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
    expect(screen.getByRole("link", { name: "Ny chatt" }).getAttribute("href")).toBe(
      "/spaces/personal/chat"
    );
    const tabs = screen.getByRole("navigation", { name: "Ytans innehåll" });
    expect(within(tabs).queryByRole("link", { name: /Medlemmar/ })).toBeNull();
    expect(within(tabs).queryByRole("link", { name: "Inställningar" })).toBeNull();
  });

  it("keeps the organization space to its four tabs, named by the h1 on its Skills tab", () => {
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
      "/spaces/organization/services",
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
    const current = within(tabs).getByRole("link", { name: "Kunskap (0)" });
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
