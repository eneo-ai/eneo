// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { setViewport } from "@/test/setup-dom";
import { renderInApp } from "@/test/render";
import type { Space } from "./space";
import { makeAssistant, makeSpace } from "./testing/space-fixture";

const state = vi.hoisted(() => ({
  space: null as unknown,
  pushed: [] as string[],
  deleted: [] as string[]
}));

vi.mock("@/lib/navigation", () => ({
  useRouter: () => ({ push: (href: string) => state.pushed.push(href), prefetch: () => {} })
}));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space as Space) };
});
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: () => Promise.resolve({ data: { items: [] }, response: new Response("{}") }),
    DELETE: (path: string, { params }: { params: { path: { id: string } } }) => {
      state.deleted.push(`${path} ${params.path.id}`);
      return Promise.resolve({ data: null, response: new Response(null, { status: 204 }) });
    }
  }
}));

import { AppsPage } from "@/features/apps/apps-page";
import { AssistantsPage } from "@/features/assistants/assistants-page";
import { ServicesPage } from "@/features/services/services-page";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  state.pushed = [];
  state.deleted = [];
});

const liveRegion = () => document.querySelector("[data-astryx-live-region='polite']");

/** The menu a MoreMenu button opens (every card has one in the DOM). */
const menuOf = (button: HTMLElement) =>
  within(document.getElementById(button.getAttribute("aria-controls")!)!);

function show(space: Space, page: React.ReactNode) {
  state.space = space;
  return renderInApp(page);
}

const assistants = [
  makeAssistant(),
  makeAssistant({ id: "a2", name: "Avtalsgranskaren", published: false, description: null })
];

describe("AssistantsPage", () => {
  it("groups cards by status for publishers, each card a link to its chat", async () => {
    const { container } = show(makeSpace({ assistants }), <AssistantsPage />);

    expect(screen.getByRole("heading", { level: 2, name: "Assistenter" })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Skapa assistent" })).toHaveLength(1);
    const published = screen.getByRole("region", { name: "Publicerad" });
    const card = within(published).getByRole("link", { name: "Upphandlingsassistenten" });
    expect(card.getAttribute("href")).toBe("/spaces/space-1/chat?type=assistant&id=assistant-1");
    expect(within(published).getByText("Svarar på frågor om LOU.")).toBeTruthy();
    expect(within(published).getByText("Haiku 4.5")).toBeTruthy();
    expect(
      within(screen.getByRole("region", { name: "Utkast" })).getByRole("link", {
        name: "Avtalsgranskaren"
      })
    ).toBeTruthy();
    await expectNoAxeViolations(container);

    fireEvent.change(screen.getByRole("textbox", { name: "Filtrera assistenter" }), {
      target: { value: "avtal" }
    });
    expect(screen.queryByRole("link", { name: "Upphandlingsassistenten" })).toBeNull();
    await waitFor(() => expect(liveRegion()?.textContent).toBe("1 träff"));
    fireEvent.change(screen.getByRole("textbox", { name: "Filtrera assistenter" }), {
      target: { value: "saknas" }
    });
    // Under the tab's h2, the empty result is an h3.
    expect(screen.getByRole("heading", { level: 3, name: "Inga resultat hittades" })).toBeTruthy();
    await waitFor(() => expect(liveRegion()?.textContent).toBe("Inga träffar"));
  });

  it.each(["cards", "list"])("keeps each %s menu apart from the resource link", (view) => {
    show(makeSpace({ assistants }), <AssistantsPage />);
    if (view === "list") fireEvent.click(screen.getByRole("button", { name: "Lista" }));
    const card = screen.getByRole("link", { name: "Upphandlingsassistenten" });
    const menu = screen.getByRole("button", {
      name: "Fler åtgärder för Upphandlingsassistenten"
    });
    // Tab order: the card's link, then its menu (document order, no tabindex tricks).
    const item = card.closest("li, tr")!;
    expect(Array.from(item.querySelectorAll("a[href], button"))).toEqual([card, menu]);
    expect(item.querySelector("[tabindex]:not([tabindex='-1']):not([tabindex='0'])")).toBeNull();

    const opened = vi.fn();
    card.addEventListener("click", opened);
    fireEvent.click(menu);
    fireEvent.click(menuOf(menu).getByRole("menuitem", { name: "Redigera" }));
    expect(opened).not.toHaveBeenCalled();
    expect(state.pushed).toEqual(["/spaces/space-1/assistants/assistant-1/edit"]);
  });

  it.each(["cards", "list"])(
    "moves focus to the heading after deleting an assistant from %s",
    async (view) => {
      show(makeSpace({ assistants }), <AssistantsPage />);
      if (view === "list") fireEvent.click(screen.getByRole("button", { name: "Lista" }));
      const menu = screen.getByRole("button", {
        name: "Fler åtgärder för Upphandlingsassistenten"
      });
      menu.focus();
      fireEvent.click(menu);
      fireEvent.click(menuOf(menu).getByRole("menuitem", { name: "Ta bort" }));
      const dialog = await screen.findByRole("alertdialog", { name: "Radera assistent" });
      // What the space holds once the assistant is gone.
      state.space = makeSpace({ assistants: [assistants[1]!] });
      fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));

      await waitFor(() => expect(state.deleted).toEqual(["/api/v1/assistants/{id}/ assistant-1"]));
      await waitFor(() =>
        expect(screen.queryByRole("link", { name: "Upphandlingsassistenten" })).toBeNull()
      );
      await waitFor(() =>
        expect(document.activeElement).toBe(
          screen.getByRole("heading", { level: 2, name: "Assistenter" })
        )
      );
    }
  );

  it("shows the status on each card for users who cannot publish", () => {
    show(
      makeSpace({ assistants, resourcePermissions: ["read", "create", "edit", "delete"] }),
      <AssistantsPage />
    );
    const cards = within(screen.getAllByRole("list")[0]!).getAllByRole("link");
    expect(cards.map((link) => link.getAttribute("aria-label"))).toEqual([
      "Avtalsgranskaren",
      "Upphandlingsassistenten"
    ]);
    expect(screen.getByText("Utkast")).toBeTruthy();
    expect(screen.getByText("Publicerad")).toBeTruthy();
  });

  it("puts the create menu in the empty state", async () => {
    const { container } = show(makeSpace(), <AssistantsPage />);
    expect(screen.getByRole("heading", { level: 3, name: "Inga assistenter ännu" })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Skapa assistent" })).toHaveLength(1);
    await expectNoAxeViolations(container);
  });
});

describe("AppsPage and ServicesPage", () => {
  it("render the same card grid", async () => {
    const space = makeSpace({
      apps: [
        {
          id: "app-1",
          name: "Protokollsammanfattning",
          description: "Sammanfattar protokoll.",
          published: true,
          user_id: "u",
          permissions: ["read", "edit", "delete"]
        }
      ],
      services: [
        {
          id: "service-1",
          name: "Klassificering",
          prompt: "…",
          output_format: "json",
          user_id: "u",
          permissions: ["read", "edit", "delete"]
        }
      ]
    });

    const apps = show(space, <AppsPage />);
    expect(screen.getByRole("link", { name: "Protokollsammanfattning" }).getAttribute("href")).toBe(
      "/spaces/space-1/apps/app-1"
    );
    expect(screen.getByText("Sammanfattar protokoll.")).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Filtrera appar" })).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Fler åtgärder för Protokollsammanfattning" })
    ).toBeTruthy();
    await expectNoAxeViolations(apps.container);
    cleanup();

    const services = show(space, <ServicesPage />);
    expect(screen.getByRole("link", { name: "Klassificering" }).getAttribute("href")).toBe(
      "/spaces/space-1/services/service-1?tab=playground"
    );
    expect(screen.getByText("JSON")).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Filtrera tjänster" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Fler åtgärder för Klassificering" })).toBeTruthy();
    await expectNoAxeViolations(services.container);
  });

  it("explain empty lists and offer the create action", () => {
    show(makeSpace(), <ServicesPage />);
    expect(screen.getByRole("heading", { level: 3, name: "Inga tjänster ännu" })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Skapa tjänst" })).toHaveLength(1);
    cleanup();

    show(makeSpace(), <AppsPage />);
    expect(screen.getByRole("heading", { level: 3, name: "Inga appar ännu" })).toBeTruthy();
  });
});

describe("Collection tabs on a phone (decision 9)", () => {
  it("list assistants as rows in their groups, apps and services too", async () => {
    setViewport("phone");
    const { container } = show(makeSpace({ assistants }), <AssistantsPage />);
    expect(screen.queryByRole("button", { name: "Lista" })).toBeNull();
    const published = screen.getByRole("region", { name: "Publicerad" });
    const row = within(published).getByRole("link", { name: /^Upphandlingsassistenten/ });
    expect(row.getAttribute("href")).toBe("/spaces/space-1/chat?type=assistant&id=assistant-1");
    expect(row.closest(".astryx-item")).toBeTruthy();
    expect(row.textContent).toContain("Svarar på frågor om LOU.");
    expect(
      within(row.closest("li")!).getByRole("button", {
        name: "Fler åtgärder för Upphandlingsassistenten"
      })
    ).toBeTruthy();
    expect(
      within(screen.getByRole("region", { name: "Utkast" })).getByRole("link", {
        name: /^Avtalsgranskaren/
      })
    ).toBeTruthy();
    await expectNoAxeViolations(container);
  });
});

for (const [Page, space] of [
  [AssistantsPage, makeSpace({ assistants })],
  [
    AppsPage,
    makeSpace({
      apps: [
        {
          id: "published-app",
          name: "Zeta",
          published: true,
          user_id: "u",
          permissions: ["read", "edit"]
        },
        { id: "draft-app", name: "Alfa", published: false, user_id: "u", permissions: ["read"] }
      ]
    })
  ]
] as const) {
  it(`${Page.name} switches to sortable lists, collapses groups and restores its view`, async () => {
    show(space, <Page />);
    const list = screen.getByRole("button", { name: "Lista" });
    list.focus();
    fireEvent.click(list);
    expect(list.getAttribute("aria-pressed")).toBe("true");
    expect(document.activeElement).toBe(list);
    const published = screen.getByRole("region", { name: "Publicerad" });
    const table = within(published).getByRole("table");
    const status = within(table).getByRole("columnheader", { name: /Status/ });
    fireEvent.click(within(status).getByRole("button"));
    fireEvent.click(within(status).getByRole("button"));
    expect(
      screen
        .getAllByRole("region")
        .filter((region) =>
          ["Publicerad", "Utkast"].includes(
            region.getAttribute("aria-label") ?? region.querySelector("h3")?.textContent ?? ""
          )
        )
        .map((region) => region.querySelector("h3")?.textContent)
    ).toEqual(["Utkast", "Publicerad"]);
    const name = within(table).getByRole("columnheader", { name: /Namn/ });
    fireEvent.click(within(name).getByRole("button"));
    const collapse = within(published).getByRole("button", { name: "Publicerad" });
    fireEvent.click(collapse);
    expect(collapse.getAttribute("aria-expanded")).toBe("false");
    expect(within(published).queryByRole("table")).toBeNull();
    fireEvent.click(collapse);
    expect(within(published).getByRole("table")).toBeTruthy();
    cleanup();
    show(space, <Page />);
    expect(screen.getByRole("button", { name: "Lista" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getAllByRole("table")).toHaveLength(2);
  });
}

it("keeps an assistant with the schema's omitted publication default in Drafts", () => {
  const draft = makeAssistant({
    id: "default-draft",
    name: "Draft by default",
    published: undefined
  });
  show(makeSpace({ assistants: [draft] }), <AssistantsPage />);
  expect(
    within(screen.getByRole("region", { name: "Utkast" })).getByRole("link", { name: draft.name })
  ).toBeTruthy();
});

it("exposes card sort choices as a checked radio group and applies the chosen direction", async () => {
  const app = { id: "z", name: "Zeta", published: true, user_id: "u", permissions: ["read"] };
  show(makeSpace({ apps: [app, { ...app, id: "a", name: "Alfa" }] }), <AppsPage />);
  const sort = screen.getByRole("button", { name: /^Sortera: Namn/ });
  fireEvent.click(sort);
  expect(
    (await screen.findByRole("menuitemradio", { name: "Namn · Stigande" })).getAttribute(
      "aria-checked"
    )
  ).toBe("true");
  fireEvent.click(screen.getByRole("menuitemradio", { name: "Namn · Fallande" }));
  expect(screen.getByRole("button", { name: "Sortera: Namn · Fallande" })).toBeTruthy();
  expect(
    within(screen.getByRole("region", { name: "Publicerad" }))
      .getAllByRole("link")
      .map((link) => link.getAttribute("aria-label"))
  ).toEqual(["Zeta", "Alfa"]);
});
