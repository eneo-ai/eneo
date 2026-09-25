// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { ChatPartner } from "@/lib/chat/types";
import { expectNoAxeViolations } from "@/test/axe";
import { HistoryAside } from "./history-panel";
import { RenameSessionDialog } from "./session-actions";
import { ChatTestProviders, installDomPolyfills } from "./testing";

const now = Date.now();
const api = vi.hoisted(() => ({
  GET: vi.fn(),
  PATCH: vi.fn(async () => ({ data: {}, response: new Response() })),
  POST: vi.fn(),
  DELETE: vi.fn()
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

beforeAll(() => {
  installDomPolyfills();
  api.GET.mockImplementation(async () => ({
    data: {
      items: [
        { id: "s1", name: "Upphandlingsanalys", updated_at: new Date(now).toISOString() },
        {
          id: "s2",
          name: "Protokoll KS",
          updated_at: new Date(now - 40 * 86_400_000).toISOString()
        }
      ],
      next_cursor: null
    },
    response: new Response()
  }));
});
afterEach(cleanup);

const partner: ChatPartner = {
  type: "assistant",
  id: "assistant-1",
  name: "Upphandlingsassistenten"
};

function renderHistory(onClose = vi.fn(), onSelect = vi.fn()) {
  render(
    <ChatTestProviders>
      <HistoryAside
        inline
        partner={partner}
        activeSessionId="s1"
        onSelect={onSelect}
        onDeleted={vi.fn()}
        onClose={onClose}
      />
    </ChatTestProviders>
  );
  return { onClose, onSelect };
}

describe("HistoryAside", () => {
  it("groups conversations by date, marks the open one and selects on click", async () => {
    const { onSelect } = renderHistory();
    const aside = screen.getByRole("complementary", { name: "Historik" });
    await waitFor(() => expect(document.activeElement?.textContent).toBe("Historik"));

    const today = await within(aside).findByRole("region", { name: "Idag" });
    const current = within(today).getByRole("button", { name: "Upphandlingsanalys" });
    expect(current.getAttribute("aria-current")).toBe("true");
    const older = within(aside).getByRole("region", { name: "Äldre" });
    fireEvent.click(within(older).getByRole("button", { name: "Protokoll KS" }));
    expect(onSelect).toHaveBeenCalledWith("s2");
  });

  it("closes on Escape", async () => {
    const { onClose } = renderHistory();
    const heading = await screen.findByRole("heading", { name: "Historik" });
    fireEvent.keyDown(heading, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("has no axe violations", async () => {
    renderHistory();
    await screen.findByRole("region", { name: "Idag" });
    await expectNoAxeViolations(document.body);
  });
});

describe("RenameSessionDialog", () => {
  it("renames with a visible label and saves on Enter", () => {
    const onSave = vi.fn();
    render(
      <ChatTestProviders>
        <RenameSessionDialog
          session={{ id: "s1", name: "Gammalt namn" }}
          pending={false}
          onCancel={vi.fn()}
          onSave={onSave}
        />
      </ChatTestProviders>
    );
    const input = screen.getByLabelText("Namn");
    fireEvent.change(input, { target: { value: "Nytt namn" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSave).toHaveBeenCalledWith("Nytt namn");
  });
});
