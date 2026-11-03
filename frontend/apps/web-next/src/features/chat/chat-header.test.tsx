// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatPartner } from "@/lib/chat/types";
import { expectNameToHoldVisibleText, expectNoAxeViolations } from "@/test/axe";
import { router } from "@/test/navigation";
import { renderInApp } from "@/test/render";
import { OPEN_NAV_EVENT } from "@/components/shell/routes";
import { ChatHeader, PartnerSwitcher } from "./chat-header";
import { CHAT_PANEL_IDS } from "./chat-url";
import type { ChatPartnerSwitcherItem } from "./partner-switcher";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));

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

/** From 768 px: what the switcher shows (the assistant, then its space and model), then what it does. */
const DESKTOP_SWITCHER = "Upphandlingsassistenten. Upphandling · Claude Haiku 4.5. Byt assistent";

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
    view: { value: "chat", onChange: vi.fn(), hasInsights: false },
    historyOpen: false,
    onToggleHistory: vi.fn(),
    onNewConversation: vi.fn(),
    menuItems: [{ label: "Byt namn på konversationen", onClick: vi.fn() }],
    ...overrides
  };
  // The tabs control the page's panels (chat-page.tsx): stand-ins here.
  return renderInApp(
    <>
      <ChatHeader {...props} />
      {Object.values(CHAT_PANEL_IDS).map((id) => (
        <div key={id} id={id} />
      ))}
    </>
  );
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
    expect(screen.getAllByRole("button", { name: DESKTOP_SWITCHER })).toHaveLength(1);
  });

  it("shows a fixed model under the partner's name from 1024px", () => {
    renderHeader();
    expect(screen.getAllByText("Upphandling · Claude Haiku 4.5")).toHaveLength(1);
    expect(within(phoneHeader()).queryByText(/Claude Haiku 4.5/)).toBeNull();
  });

  it("switches assistant from a menu that marks the current one as selected", async () => {
    renderHeader();
    const [trigger] = screen.getAllByRole("button", { name: DESKTOP_SWITCHER });
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

  it("shows the phone header on a phone, held either way, and the full one beside the side navigation", () => {
    renderHeader();
    const phone = screen.getByRole("button", { name: "Öppna menyn" }).parentElement!;
    expect(phone.className).toContain("wide:hidden");
    // The full header's h1 is shown; the phone's is for assistive technology only.
    const full = screen
      .getAllByRole("heading", { level: 1 })
      .find((heading) => !heading.classList.contains("sr-only"))!
      .closest<HTMLElement>("[class*='wide:flex']")!;
    expect(full.className).toContain("wide:flex");
    expect(full.className).not.toContain("lg:flex");
  });

  it("asks the app shell to open its navigation from the phone header", () => {
    const listener = vi.fn();
    window.addEventListener(OPEN_NAV_EVENT, listener);
    renderHeader();
    fireEvent.click(screen.getByRole("button", { name: "Öppna menyn" }));
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(OPEN_NAV_EVENT, listener);
  });

  it("switches Chatt, Historik and Insikter as tabs, as Svelte's chat page does", () => {
    const onChange = vi.fn();
    renderHeader({ view: { value: "chat", onChange, hasInsights: true } });
    const tabs = screen.getByRole("tablist", { name: /^Huvudvyer/ });
    const tab = (name: string) => within(tabs).getByRole("tab", { name });
    expect(tab("Chatt").getAttribute("aria-selected")).toBe("true");
    expect(tab("Historik").getAttribute("aria-controls")).toBe(CHAT_PANEL_IDS.history);
    fireEvent.click(tab("Historik"));
    expect(onChange).toHaveBeenCalledWith("history");
    fireEvent.click(tab("Insikter"));
    expect(onChange).toHaveBeenCalledWith("insights");
  });

  it("offers Insikter only where the partner has them", () => {
    renderHeader();
    expect(within(screen.getByRole("tablist")).queryByRole("tab", { name: "Insikter" })).toBeNull();
  });

  it("starts a new conversation from its primary button and links the editor", () => {
    const onNewConversation = vi.fn();
    renderHeader({ onNewConversation, editHref: "/spaces/s/assistants/assistant-1/edit" });
    const create = screen.getAllByRole("button", { name: "Ny konversation" })[0]!;
    expect(create.dataset.variant).toBe("primary");
    fireEvent.click(create);
    expect(onNewConversation).toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "Redigera" }).getAttribute("href")).toBe(
      "/spaces/s/assistants/assistant-1/edit"
    );
  });

  it("names the personal assistant where Svelte's chat page does", () => {
    renderHeader({
      partner: { type: "default-assistant", id: "p", name: "Eneo", personalSpace: true }
    });
    const wide = screen.getByRole("tablist").closest<HTMLElement>("[class*='wide:flex']")!;
    expect(within(wide).getByText("Personlig assistent")).toBeTruthy();
  });

  it("opens Felsökning once a saved answer exists, and says why it waits before", () => {
    const onOpen = vi.fn();
    renderHeader({ debug: { isEnabled: false, onOpen } });
    const debug = screen.getByRole("button", { name: "Felsökning" });
    fireEvent.click(debug);
    expect(onOpen).not.toHaveBeenCalled();
    cleanup();
    renderHeader({ debug: { isEnabled: true, onOpen } });
    fireEvent.click(screen.getByRole("button", { name: "Felsökning" }));
    expect(onOpen).toHaveBeenCalledWith(screen.getByRole("button", { name: "Felsökning" }));
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
      name: "Upphandlingsanalys mot LOU. Upphandlingsassistenten Intern. I Upphandling. Byt assistent"
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
        name: "Upphandlingsassistenten Upphandling Intern. Byt assistent"
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

  it("starts each switcher's name with what it shows, in order, so a voice command reaches it (WCAG 2.5.3)", () => {
    const names = {
      titled:
        "Upphandlingsanalys mot LOU. Upphandlingsassistenten Intern. I Upphandling. Byt assistent",
      untitled: "Upphandlingsassistenten Upphandling Intern. Byt assistent"
    };
    for (const [variant, name] of Object.entries(names)) {
      renderHeader(variant === "titled" ? {} : { title: null });
      expectNameToHoldVisibleText(within(phoneHeader()).getByRole("button", { name }), name);
      expectNameToHoldVisibleText(
        screen.getByRole("button", { name: DESKTOP_SWITCHER }),
        DESKTOP_SWITCHER
      );
      cleanup();
    }
  });

  it("names the composer's assistant token by the name it shows, then what it does", () => {
    const name = "Upphandlingsassistenten. Byt assistent";
    renderInApp(
      <PartnerSwitcher partner={partner} items={items} subtitle={null} variant="token" />
    );
    expectNameToHoldVisibleText(screen.getByRole("button", { name }), name);
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
