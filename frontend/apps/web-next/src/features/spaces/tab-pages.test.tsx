// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { Space } from "./space";
import { makeAssistant, makeSpace } from "./testing/space-fixture";

const state = vi.hoisted(() => ({
  space: null as unknown,
  pushed: [] as string[],
  deleted: [] as string[]
}));

vi.mock("next/navigation", () => ({
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

  it("keeps each card's named menu apart from the card's link", () => {
    show(makeSpace({ assistants }), <AssistantsPage />);
    const card = screen.getByRole("link", { name: "Upphandlingsassistenten" });
    const menu = screen.getByRole("button", {
      name: "Fler åtgärder för Upphandlingsassistenten"
    });
    // Tab order: the card's link, then its menu (document order, no tabindex tricks).
    const item = card.closest("li")!;
    expect(Array.from(item.querySelectorAll("a[href], button"))).toEqual([card, menu]);
    expect(item.querySelector("[tabindex]:not([tabindex='-1']):not([tabindex='0'])")).toBeNull();

    const opened = vi.fn();
    card.addEventListener("click", opened);
    fireEvent.click(menu);
    fireEvent.click(menuOf(menu).getByRole("menuitem", { name: "Redigera" }));
    expect(opened).not.toHaveBeenCalled();
    expect(state.pushed).toEqual(["/spaces/space-1/assistants/assistant-1/edit"]);
  });

  it("moves focus to the heading when a deleted assistant's card goes away", async () => {
    show(makeSpace({ assistants }), <AssistantsPage />);
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
  });

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
