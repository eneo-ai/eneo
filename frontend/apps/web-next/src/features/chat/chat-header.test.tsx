// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { ChatPartner } from "@/lib/chat/types";
import { expectNoAxeViolations } from "@/test/axe";
import { OPEN_NAV_EVENT } from "@/components/shell/routes";
import { ChatHeader } from "./chat-header";
import type { ChatPartnerSwitcherItem } from "./partner-switcher";
import { ChatTestProviders, installDomPolyfills } from "./testing";

const router = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

beforeAll(() => installDomPolyfills());
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
  return render(
    <ChatTestProviders>
      <ChatHeader {...props} />
    </ChatTestProviders>
  );
}

describe("ChatHeader", () => {
  it("shows the conversation title as the page heading and the security classification", () => {
    renderHeader();
    // Desktop h1 and the phone header's visually hidden one (only one is displayed).
    expect(
      screen.getAllByRole("heading", { level: 1, name: "Upphandlingsanalys mot LOU" })
    ).toHaveLength(2);
    expect(screen.getByText("Intern")).toBeTruthy();
    expect(
      screen.getAllByRole("button", { name: /byt assistent: upphandlingsassistenten/i }).length
    ).toBeGreaterThan(0);
  });

  it("shows a fixed model under the partner's name on every width", () => {
    renderHeader();
    // Desktop header and phone header (only one is displayed).
    expect(screen.getAllByText("Upphandling · Claude Haiku 4.5")).toHaveLength(2);
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
    const history = screen.getByRole("button", { name: "Historik" });
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
