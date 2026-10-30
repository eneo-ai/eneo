// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { createRef, useState, type Ref } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatPartner } from "@/lib/chat/types";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { Composer, type ComposerHandle } from "./composer";
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
  inputRef
}: {
  busy?: boolean;
  onSubmit?: () => void;
  onStop?: () => void;
  initial?: string;
  sendBlocked?: string | null;
  inputRef?: Ref<ComposerHandle>;
}) {
  const [value, setValue] = useState(initial);
  const attachments = useAttachments(partner);
  return (
    <Composer
      value={value}
      onChange={setValue}
      onSubmit={onSubmit}
      sendBlocked={sendBlocked}
      busy={busy}
      onStop={onStop}
      label="Fråga Upphandlingsassistenten"
      placeholder="Fråga Upphandlingsassistenten"
      attachments={attachments}
      onOpenFileDialog={vi.fn()}
      knowledge={partner.knowledge}
      inputRef={inputRef}
      triggers={inputRef ? [] : undefined}
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
  it("is a named multi-line text field with the keyboard hint as its description", () => {
    renderComposer();
    const textarea = screen.getByRole("textbox", { name: "Fråga Upphandlingsassistenten" });
    expect(textarea.tagName).toBe("TEXTAREA");
    expect(descriptionOf(textarea)).toBe(
      "Retur ger en ny rad. Skicka med Skicka-knappen, Kommando+Retur eller Ctrl+Retur."
    );
  });

  it("adds a line on Return and sends on ⌘ or Ctrl+Return and with Send (decision 3)", () => {
    const onSubmit = vi.fn();
    renderComposer({ onSubmit, initial: "Hej" });
    const textarea = screen.getByRole("textbox");

    // Return and Shift+Return keep the textarea's own newline.
    expect(fireEvent.keyDown(textarea, { key: "Enter" })).toBe(true);
    expect(fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true })).toBe(true);
    expect(onSubmit).not.toHaveBeenCalled();

    expect(fireEvent.keyDown(textarea, { key: "Enter", metaKey: true })).toBe(false);
    expect(fireEvent.keyDown(textarea, { key: "Enter", ctrlKey: true })).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Skicka meddelande" }));
    expect(onSubmit).toHaveBeenCalledTimes(3);
  });

  it.each([false, true])("does not send during composition (references: %s)", (references) => {
    const onSubmit = vi.fn();
    renderComposer({
      onSubmit,
      initial: "にほん",
      inputRef: references ? createRef<ComposerHandle>() : undefined
    });
    const textarea = screen.getByRole("textbox");
    fireEvent.compositionStart(textarea);
    fireEvent.keyDown(textarea, { key: "Enter", ctrlKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.compositionEnd(textarea);
    fireEvent.keyDown(textarea, { key: "Enter", ctrlKey: true });
    expect(onSubmit).toHaveBeenCalledOnce();
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

  it("counts a pill put in from outside as content: placeholder gone, Send enabled", () => {
    const ref = createRef<ComposerHandle>();
    renderInApp(<Harness inputRef={ref} />);
    const textbox = screen.getByRole("textbox");
    expect(textbox.parentElement?.textContent).toContain("Fråga Upphandlingsassistenten");
    act(() => {
      ref.current?.insertToken({ value: "{{step_1.output.text}}", render: () => <b>pill</b> });
    });
    expect(
      textbox.querySelector("[data-astryx-token-value]")?.getAttribute("data-astryx-token-value")
    ).toBe("{{step_1.output.text}}");
    expect(textbox.parentElement?.textContent).not.toContain("Fråga Upphandlingsassistenten");
    expect(screen.getByRole("button", { name: "Skicka meddelande" }).hasAttribute("disabled")).toBe(
      false
    );
  });

  it("has no axe violations", async () => {
    const { container } = renderComposer({ initial: "Hej" });
    await expectNoAxeViolations(container);
  });
});
