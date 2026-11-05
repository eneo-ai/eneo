// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatPartner } from "@/lib/chat/types";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { PHONE_VIEWPORT, setViewport } from "@/test/setup-dom";
import { Composer } from "./composer";
import { useAttachments } from "./use-attachments";

afterEach(cleanup);

const partner: ChatPartner = {
  type: "assistant",
  id: "assistant-1",
  name: "Upphandlingsassistenten",
  knowledge: [{ id: "g1", name: "Upphandling", kind: "collection" }]
};

function Harness({
  busy = false,
  onSubmit = vi.fn(),
  onStop = vi.fn(),
  initial = "",
  sendBlocked = null,
  unavailable = null,
  knowledgeMode,
  beforeAnswer = false
}: {
  busy?: boolean;
  onSubmit?: () => void;
  onStop?: () => void;
  initial?: string;
  sendBlocked?: string | null;
  unavailable?: string | null;
  knowledgeMode?: "tool" | "inject";
  beforeAnswer?: boolean;
}) {
  const [value, setValue] = useState(initial);
  const attachments = useAttachments(partner);
  return (
    <Composer
      value={value}
      onChange={setValue}
      onSubmit={onSubmit}
      sendBlocked={sendBlocked}
      unavailable={unavailable}
      busy={busy}
      onStop={onStop}
      label="Fråga Upphandlingsassistenten"
      placeholder="Fråga Upphandlingsassistenten"
      attachments={attachments}
      onOpenFileDialog={vi.fn()}
      knowledge={partner.knowledge}
      knowledgeMode={knowledgeMode}
      beforeAnswer={beforeAnswer}
    />
  );
}

function renderComposer(props: Parameters<typeof Harness>[0] = {}) {
  return renderInApp(<Harness {...props} />);
}

/** The text of the elements a field's aria-describedby points at. */
function descriptionOf(element: Element) {
  return (element.getAttribute("aria-describedby") ?? "")
    .split(" ")
    .filter(Boolean)
    .map((id) => document.getElementById(id)?.textContent ?? "")
    .join(" ");
}

describe("Composer", () => {
  it("is a named textarea with the keyboard hint as its description", () => {
    renderComposer();
    const textarea = screen.getByRole("textbox", { name: "Fråga Upphandlingsassistenten" });
    expect(textarea.tagName).toBe("TEXTAREA");
    expect(descriptionOf(textarea)).toBe(
      "Retur skickar och Skift+Retur ger en ny rad. Kommando+Retur, Ctrl+Retur och Skicka-knappen skickar också."
    );
    // The keys sit on Send's tooltip, not in the footer row, where they crowded it.
    expect(document.querySelector("kbd")).toBeNull();
    expect(screen.getByText("Skicka (Retur). Skift+Retur ger en ny rad.")).toBeTruthy();
  });

  it("does not point a touch screen at keys it does not have in the field's description", () => {
    setViewport(PHONE_VIEWPORT);
    renderComposer();
    const textarea = screen.getByRole("textbox", { name: "Fråga Upphandlingsassistenten" });
    expect(descriptionOf(textarea)).toBe("Retur ger en ny rad. Skicka med Skicka-knappen.");
  });

  it("leaves the assistant switcher pill out below 768 px, where the header has it", () => {
    renderInApp(
      <Composer
        value=""
        onChange={vi.fn()}
        onSubmit={vi.fn()}
        sendBlocked={null}
        busy={false}
        onStop={vi.fn()}
        label="Fråga"
        placeholder="Fråga"
        attachments={{ attachments: [] } as unknown as ReturnType<typeof useAttachments>}
        onOpenFileDialog={vi.fn()}
        knowledge={[]}
        partnerToken={<button type="button">Byt assistent</button>}
      />
    );
    expect(
      screen.getByRole("button", { name: "Byt assistent" }).parentElement?.className
    ).toContain("max-md:hidden");
  });

  it("sends on Return with a keyboard, adds a line on Shift+Return, and still sends on ⌘ or Ctrl+Return and Send", () => {
    const onSubmit = vi.fn();
    renderComposer({ onSubmit, initial: "Hej" });
    const textarea = screen.getByRole("textbox");

    // Shift+Return keeps the textarea's own newline.
    expect(fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true })).toBe(true);
    expect(onSubmit).not.toHaveBeenCalled();

    expect(fireEvent.keyDown(textarea, { key: "Enter" })).toBe(false);
    expect(fireEvent.keyDown(textarea, { key: "Enter", metaKey: true })).toBe(false);
    expect(fireEvent.keyDown(textarea, { key: "Enter", ctrlKey: true })).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Skicka meddelande" }));
    expect(onSubmit).toHaveBeenCalledTimes(4);
  });

  it.each(["phone", "tablet-portrait", "tablet-landscape"] as const)(
    "adds a line on Return on a touch screen (%s), where Send and ⌘ or Ctrl+Return send",
    (viewport) => {
      setViewport(viewport);
      const onSubmit = vi.fn();
      renderComposer({ onSubmit, initial: "Hej" });
      const textarea = screen.getByRole("textbox");
      expect(fireEvent.keyDown(textarea, { key: "Enter" })).toBe(true);
      expect(onSubmit).not.toHaveBeenCalled();
      expect(fireEvent.keyDown(textarea, { key: "Enter", ctrlKey: true })).toBe(false);
      expect(onSubmit).toHaveBeenCalledTimes(1);
    }
  );

  it("does not send a word being composed with an input method", () => {
    const onSubmit = vi.fn();
    renderComposer({ onSubmit, initial: "にほん" });
    const textarea = screen.getByRole("textbox");
    // Return that commits a candidate: flagged, or keyCode 229 (Safari, after compositionend).
    for (const ctrlKey of [false, true]) {
      expect(fireEvent.keyDown(textarea, { key: "Enter", ctrlKey, isComposing: true })).toBe(true);
      expect(fireEvent.keyDown(textarea, { key: "Enter", ctrlKey, keyCode: 229 })).toBe(true);
    }
    fireEvent.compositionStart(textarea);
    expect(fireEvent.keyDown(textarea, { key: "Enter" })).toBe(true);
    expect(fireEvent.keyDown(textarea, { key: "Enter", ctrlKey: true })).toBe(true);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("says what is missing at the field when Return sends an empty draft, and sends nothing while answering", () => {
    const onSubmit = vi.fn();
    const { unmount } = renderComposer({ onSubmit });
    const textarea = screen.getByRole("textbox");
    textarea.focus();
    expect(fireEvent.keyDown(textarea, { key: "Enter" })).toBe(false);
    expect(onSubmit).not.toHaveBeenCalled();
    expect(descriptionOf(textarea)).toContain("Skriv en fråga först.");
    expect(document.activeElement).toBe(textarea);
    unmount();

    renderComposer({ onSubmit, busy: true, initial: "Nästa fråga" });
    expect(fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" })).toBe(false);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("keeps Send enabled and says at the field what is missing, with focus in it (decision 44)", async () => {
    const onSubmit = vi.fn();
    renderComposer({ onSubmit });
    const textarea = screen.getByRole("textbox");
    const send = screen.getByRole("button", { name: "Skicka meddelande" });
    expect(send.hasAttribute("disabled")).toBe(false);
    expect(send.getAttribute("aria-disabled")).not.toBe("true");

    fireEvent.click(send);
    expect(onSubmit).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(textarea);
    expect(textarea.getAttribute("aria-invalid")).toBe("true");
    expect(descriptionOf(textarea)).toContain("Skriv en fråga först.");
    // Announced too: the text appears where the user is not looking.
    await waitFor(() =>
      expect(
        [...document.querySelectorAll("[aria-live]")].some((region) =>
          region.textContent?.includes("Skriv en fråga först.")
        )
      ).toBe(true)
    );

    // Typing clears it.
    fireEvent.change(textarea, { target: { value: "H" } });
    expect(textarea.getAttribute("aria-invalid")).toBeNull();
    expect(descriptionOf(textarea)).not.toContain("Skriv en fråga först.");
  });

  it("says why it cannot send when the caller blocks it, and keeps the draft", () => {
    const onSubmit = vi.fn();
    renderComposer({ onSubmit, initial: "Lång fråga", sendBlocked: "Konversationen är full." });
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    act(() => {
      fireEvent.keyDown(textarea, { key: "Enter", ctrlKey: true });
    });
    expect(onSubmit).not.toHaveBeenCalled();
    expect(descriptionOf(textarea)).toContain("Konversationen är full.");
    expect(textarea.value).toBe("Lång fråga");
  });

  it("keeps the caller's reason at the field only while it holds", () => {
    const { rerender } = renderComposer({ initial: "Fråga", sendBlocked: "Sparar…" });
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.click(screen.getByRole("button", { name: "Skicka meddelande" }));
    expect(textarea.getAttribute("aria-invalid")).toBe("true");

    rerender(<Harness initial="Fråga" sendBlocked="Inställningarna kunde inte sparas." />);
    expect(descriptionOf(textarea)).toContain("Inställningarna kunde inte sparas.");
    expect(descriptionOf(textarea)).not.toContain("Sparar…");

    rerender(<Harness initial="Fråga" sendBlocked={null} />);
    expect(textarea.getAttribute("aria-invalid")).toBeNull();
    expect(descriptionOf(textarea)).not.toContain("Inställningarna kunde inte sparas.");

    // A later reason is the user's to meet on their next try, not before.
    rerender(<Harness initial="Fråga" sendBlocked="Sparar…" />);
    expect(textarea.getAttribute("aria-invalid")).toBeNull();
    expect(descriptionOf(textarea)).not.toContain("Sparar…");
  });

  it("says from the start that nobody can answer, and does not send, with the draft kept", async () => {
    const onSubmit = vi.fn();
    const { container } = renderComposer({
      onSubmit,
      initial: "Hej",
      unavailable: "Ingen AI-modell tillgänglig."
    });
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    // Read with the field, not as the user's mistake.
    expect(descriptionOf(textarea)).toContain("Ingen AI-modell tillgänglig.");
    expect(textarea.getAttribute("aria-invalid")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Skicka meddelande" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(textarea.value).toBe("Hej");
    expect(document.activeElement).toBe(textarea);
    expect(screen.getAllByText("Ingen AI-modell tillgänglig.")).toHaveLength(1);
    await waitFor(() =>
      expect(
        [...document.querySelectorAll("[aria-live]")].some((region) =>
          region.textContent?.includes("Ingen AI-modell tillgänglig.")
        )
      ).toBe(true)
    );
    await expectNoAxeViolations(container);
  });

  it("is one group for the toasts to clear, so Send stays in view while the user types", () => {
    renderComposer();
    const textarea = screen.getByRole("textbox");
    // src/components/ui/toast-lift.ts raises the toasts above the whole group.
    const group = textarea.closest("[data-clear-of-toasts]");
    expect(group).not.toBeNull();
    expect(group?.contains(screen.getByRole("button", { name: "Skicka meddelande" }))).toBe(true);
    expect(group?.contains(screen.getByRole("button", { name: "Bifoga filer" }))).toBe(true);
  });

  it("turns send into a keyboard-reachable stop button while generating", () => {
    const onStop = vi.fn();
    const onSubmit = vi.fn();
    renderComposer({ busy: true, onStop, onSubmit, initial: "Nästa fråga" });
    const stop = screen.getByRole("button", { name: "Stoppa generering" });
    expect(stop.hasAttribute("disabled")).toBe(false);
    fireEvent.click(stop);
    expect(onStop).toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter", ctrlKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("shows the knowledge and attach pills and the data-sovereignty note", () => {
    renderComposer();
    expect(screen.getByRole("button", { name: /Kunskap: Upphandling/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Bifoga filer" })).toBeTruthy();
    expect(
      screen.getByText(
        "Data behandlas inom er infrastruktur. Kontrollera viktiga uppgifter mot källorna."
      )
    ).toBeTruthy();
  });

  it("says only where the data stays before the first answer, and adds the advice to check it after", () => {
    renderComposer({ beforeAnswer: true });
    expect(screen.getByText("Data behandlas inom er infrastruktur")).toBeTruthy();
    expect(screen.queryByText(/Kontrollera viktiga uppgifter/)).toBeNull();
  });

  it("has no axe violations", async () => {
    const { container } = renderComposer({ initial: "Hej" });
    await expectNoAxeViolations(container);
  });
});

it.each([
  ["inject", "Innehåll från dessa källor infogas i varje meddelande."],
  ["tool", "Assistenten söker i dessa källor när frågan kräver det."]
] as const)("explains the configured knowledge mode: %s", async (mode, hint) => {
  renderInApp(<Harness knowledgeMode={mode} />);
  fireEvent.click(screen.getByRole("button", { name: /Kunskap: Upphandling/ }));
  expect(await screen.findByText(hint)).toBeTruthy();
});
