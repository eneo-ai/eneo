// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { makeAssistant, makeSpace } from "@/features/spaces/testing/space-fixture";
import { GroupChatAssistantList } from "./assistant-list";
import type { GroupChatAssistant } from "./use-group-chat";

const space = makeSpace({
  assistants: [
    makeAssistant({ id: "missing", name: "Upphandling", description: null }),
    makeAssistant({ id: "default", name: "Ekonomi", description: "Svarar på ekonomifrågor" })
  ]
});
vi.mock("@/features/spaces/use-space", () => ({ useSpace: () => ({ space }) }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
afterEach(cleanup);

function show(selected: GroupChatAssistant[] = []) {
  const onChange = vi.fn();
  renderInApp(<GroupChatAssistantList selected={selected} onChange={onChange} />);
  return onChange;
}

async function pick(name = "Upphandling") {
  fireEvent.click(screen.getByRole("button", { name: "Lägg till assistent" }));
  screen.getByRole("combobox").focus();
  fireEvent.click(await screen.findByRole("option", { name }));
  return screen.findByRole("dialog", { name });
}

describe("group chat responsibility descriptions", () => {
  it("requires a description before adding an assistant without a default", async () => {
    const change = show();
    const dialog = await pick();
    const field = within(dialog).getByRole("textbox", { name: /Beskriv ansvar/ });
    expect(change).not.toHaveBeenCalled();
    fireEvent.change(field, { target: { value: "   " } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till i grupp" }));
    expect(change).not.toHaveBeenCalled();
    expect(field.getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(field);
    expect(within(dialog).getByText(/Beskrivning krävs för att lägga till/)).toBeTruthy();
    await expectNoAxeViolations(dialog);

    fireEvent.change(field, { target: { value: "  Ansvarar för upphandlingsfrågor.  " } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till i grupp" }));
    expect(change).toHaveBeenCalledExactlyOnceWith([
      {
        id: "missing",
        handle: "Upphandling",
        default_description: null,
        user_description: "Ansvarar för upphandlingsfrågor."
      }
    ]);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Lägg till assistent" })
    );
  });

  it("lets a new assistant use its default description without an override", async () => {
    const change = show();
    const dialog = await pick("Ekonomi");
    const field = within(dialog).getByRole("textbox", { name: /Beskriv ansvar/ });
    expect(field.getAttribute("placeholder")).toBe("Svarar på ekonomifrågor");
    fireEvent.click(within(dialog).getByRole("button", { name: "Lägg till i grupp" }));
    expect(change).toHaveBeenCalledExactlyOnceWith([
      {
        id: "default",
        handle: "Ekonomi",
        default_description: "Svarar på ekonomifrågor",
        user_description: null
      }
    ]);
  });

  it("cancels an addition without changing the list and discards its draft", async () => {
    const change = show();
    const dialog = await pick();
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "Utkast" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));
    expect(change).not.toHaveBeenCalled();
    const reopened = await pick();
    expect(within(reopened).getByRole("textbox")).toHaveProperty("value", "");
  });

  it("keeps an existing description until an empty edit is corrected", async () => {
    const change = show([
      {
        id: "missing",
        handle: "Upphandling",
        default_description: null,
        user_description: "Ansvar"
      }
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Redigera" }));
    const dialog = await screen.findByRole("dialog", { name: "Upphandling" });
    const field = within(dialog).getByRole("textbox", { name: /Beskrivning/ });
    fireEvent.change(field, { target: { value: "" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Spara" }));
    expect(change).not.toHaveBeenCalled();
    expect(within(dialog).getByText(/En beskrivning krävs för denna assistent/)).toBeTruthy();
    expect(document.activeElement).toBe(field);
    fireEvent.change(field, { target: { value: "Nytt ansvar" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Spara" }));
    expect(change).toHaveBeenCalledExactlyOnceWith([
      expect.objectContaining({ user_description: "Nytt ansvar" })
    ]);
  });

  it("allows clearing an override when the assistant has a default description", async () => {
    const change = show([
      {
        id: "default",
        handle: "Ekonomi",
        default_description: "Standard",
        user_description: "Eget"
      }
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Redigera" }));
    const dialog = await screen.findByRole("dialog", { name: "Ekonomi" });
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "   " } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Spara" }));
    expect(change).toHaveBeenCalledExactlyOnceWith([
      expect.objectContaining({ user_description: null })
    ]);
  });
});
