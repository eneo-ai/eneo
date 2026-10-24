// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatPartner } from "@/lib/chat/types";
import { expectNoAxeViolations } from "@/test/axe";
import { router } from "@/test/navigation";
import { renderInApp } from "@/test/render";
import { OPEN_NAV_EVENT } from "@/components/shell/routes";
import { ChatHeader } from "./chat-header";
import type { ChatPartnerSwitcherItem } from "./partner-switcher";

vi.mock("next/navigation", () => import("@/test/navigation"));

afterEach(cleanup);

const partner: ChatPartner = {
  type: "assistant",
  id: "assistant-1",
  name: "Upphandlingsassistenten",
  spaceName: "Upphandling",
  securityClassification: "Intern"
};

const items: ChatPartnerSwitcherItem[] = [
  {
    id: "p",
    type: "default-assistant",
    name: "Personlig assistent",
    href: "/spaces/s/chat",
    active: false
  },
  {
    id: "assistant-1",
    type: "assistant",
    name: "Upphandlingsassistenten",
    href: "/spaces/s/chat?type=assistant&id=assistant-1",
    active: true
  }
];

/** The header below 1024px: it replaces the shell's top bar (both are in jsdom's DOM). */
function phoneHeader() {
  return document.querySelector<HTMLElement>("[data-own-mobile-header]")!;
}

function renderHeader(overrides: Partial<Parameters<typeof ChatHeader>[0]> = {}) {
  const props: Parameters<typeof ChatHeader>[0] = {
    partner,
    switcherItems: items,
    title: "Upphandlingsanalys mot LOU",
    modelName: "Claude Haiku 4.5",
    historyOpen: false,
    onToggleHistory: vi.fn(),
    onNewConversation: vi.fn(),
    menuItems: [{ label: "Byt namn på konversationen", onClick: vi.fn() }],
    ...overrides
  };
  return renderInApp(<ChatHeader {...props} />);
}

describe("ChatHeader", () => {
  it("shows the conversation title as the page heading and the security classification", () => {
    renderHeader();
    // Desktop h1 and the phone header's visually hidden one (only one is displayed).
    expect(
      screen.getAllByRole("heading", { level: 1, name: "Upphandlingsanalys mot LOU" })
    ).toHaveLength(2);
    // Desktop pill and phone line (only one is displayed), read with their prefix.
    const classes = screen.getAllByText("Intern");
    expect(classes).toHaveLength(2);
    for (const element of classes) {
      expect(element.parentElement!.textContent).toBe("Säkerhetsklass: Intern");
    }
    expect(
      screen.getAllByRole("button", { name: /byt assistent: upphandlingsassistenten/i }).length
    ).toBeGreaterThan(0);
  });

  it("shows a fixed model under the partner's name from 1024px", () => {
    renderHeader();
    expect(screen.getAllByText("Upphandling · Claude Haiku 4.5")).toHaveLength(1);
    expect(within(phoneHeader()).queryByText(/Claude Haiku 4.5/)).toBeNull();
  });

  it("switches assistant from a menu that marks the current one as selected", async () => {
    renderHeader();
    const [trigger] = screen.getAllByRole("button", {
      name: "Byt assistent: Upphandlingsassistenten"
    });
    expect(trigger!.getAttribute("aria-haspopup")).toBe("menu");
    fireEvent.click(trigger!);
    const menu = document.getElementById(trigger!.getAttribute("aria-controls") ?? "")!;
    const group = within(menu).getByRole("group", { name: "Välj en assistent" });
    const current = within(group).getByRole("menuitemradio", { name: /Upphandlingsassistenten/ });
    expect(current.getAttribute("aria-checked")).toBe("true");
    const personal = within(group).getByRole("menuitemradio", { name: /Personlig assistent/ });
    expect(personal.getAttribute("aria-checked")).toBe("false");
    await expectNoAxeViolations(menu);

    fireEvent.click(personal);
    expect(router.push).toHaveBeenCalledWith("/spaces/s/chat");
  });

  it("renders no heading in the start state (the greeting is the h1 there)", () => {
    renderHeader({ title: null });
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
  });

  it("asks the app shell to open its navigation from the phone header", () => {
    const listener = vi.fn();
    window.addEventListener(OPEN_NAV_EVENT, listener);
    renderHeader();
    fireEvent.click(screen.getByRole("button", { name: "Öppna menyn" }));
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(OPEN_NAV_EVENT, listener);
  });

  it("exposes history as a disclosure and starts new conversations", () => {
    const onToggleHistory = vi.fn();
    const onNewConversation = vi.fn();
    renderHeader({ historyOpen: true, onToggleHistory, onNewConversation });
    // Named after what it opens; aria-expanded carries the state.
    const history = screen.getByRole("button", {
      name: "Konversationer med Upphandlingsassistenten"
    });
    expect(history.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(history);
    expect(onToggleHistory).toHaveBeenCalled();
    fireEvent.click(screen.getAllByRole("button", { name: "Ny konversation" })[0]!);
    expect(onNewConversation).toHaveBeenCalled();
  });

  it("has no axe violations", async () => {
    const { container } = renderHeader();
    await expectNoAxeViolations(container);
  });
});

describe("ChatHeader below 1024px (decision 2)", () => {
  it("puts the conversation title first, then the assistant and its security class", async () => {
    renderHeader();
    const header = phoneHeader();
    const switcher = within(header).getByRole("button", {
      name: "Upphandlingsanalys mot LOU. Upphandlingsassistenten i Upphandling, säkerhetsklass Intern. Byt assistent"
    });
    // What the name says, the switcher shows: the title, then the assistant and the class.
    expect(switcher.textContent).toMatch(
      /^Upphandlingsanalys mot LOU.*Upphandlingsassistenten.*Intern/
    );
    expect(
      within(header).getAllByRole("heading", { level: 1, name: "Upphandlingsanalys mot LOU" })
    ).toHaveLength(1);
    fireEvent.click(switcher);
    const menu = document.getElementById(switcher.getAttribute("aria-controls") ?? "")!;
    expect(within(menu).getByRole("group", { name: "Välj en assistent" })).toBeTruthy();
    await expectNoAxeViolations(header);
  });

  it("names the assistant first before a conversation starts", () => {
    renderHeader({ title: null });
    expect(
      within(phoneHeader()).getByRole("button", {
        name: "Upphandlingsassistenten i Upphandling, säkerhetsklass Intern. Byt assistent"
      })
    ).toBeTruthy();
    expect(within(phoneHeader()).queryByRole("heading")).toBeNull();
  });

  it("does not repeat a title's own punctuation or name the personal space", () => {
    renderHeader({
      partner: {
        type: "default-assistant",
        id: "p",
        name: "",
        personalSpace: true,
        spaceName: "Personligt"
      },
      title: "Hur långt har ärende BN 2026-0412 kommit?"
    });
    expect(
      within(phoneHeader()).getByRole("button", {
        name: "Hur långt har ärende BN 2026-0412 kommit? Personlig assistent. Byt assistent"
      })
    ).toBeTruthy();
  });

  it("shows the same lines without a menu when there is no other assistant to switch to", () => {
    renderHeader({ switcherItems: [items[1]!] });
    const header = phoneHeader();
    expect(within(header).queryByRole("button", { name: /Byt assistent/ })).toBeNull();
    // Read in full: the space, hidden for room, and the class with its prefix.
    expect(header.textContent).toContain("Upphandlingsassistenten");
    expect(header.textContent).toContain("Upphandling");
    expect(header.textContent).toContain("Säkerhetsklass: Intern");
  });
});
