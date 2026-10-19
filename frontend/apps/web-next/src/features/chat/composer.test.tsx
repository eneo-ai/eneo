// @vitest-environment jsdom
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatPartner } from "@/lib/chat/types";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
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
  initial = ""
}: {
  busy?: boolean;
  onSubmit?: () => void;
  onStop?: () => void;
  initial?: string;
}) {
  const [value, setValue] = useState(initial);
  const attachments = useAttachments(partner);
  return (
    <Composer
      value={value}
      onChange={setValue}
      onSubmit={onSubmit}
      canSubmit={value.trim().length > 0}
      busy={busy}
      onStop={onStop}
      label="Meddelande till Upphandlingsassistenten"
      placeholder="Fråga, klistra in text eller släpp filer här"
      attachments={attachments}
      onOpenFileDialog={vi.fn()}
      knowledge={partner.knowledge}
    />
  );
}

function renderComposer(props: Parameters<typeof Harness>[0] = {}) {
  return renderInApp(<Harness {...props} />);
}

describe("Composer", () => {
  it("is a named textarea with the keyboard hint as its description", () => {
    renderComposer();
    const textarea = screen.getByRole("textbox", {
      name: "Meddelande till Upphandlingsassistenten"
    });
    expect(textarea.tagName).toBe("TEXTAREA");
    const hint = document.getElementById(textarea.getAttribute("aria-describedby") ?? "");
    expect(hint?.textContent).toBe("Enter skickar, Skift+Enter ger en ny rad.");
  });

  it("sends on Enter, not on Shift+Enter, and only with text", () => {
    const onSubmit = vi.fn();
    renderComposer({ onSubmit });
    const textarea = screen.getByRole("textbox");
    const send = screen.getByRole("button", { name: "Skicka meddelande" });
    expect(send.hasAttribute("disabled")).toBe(true);

    fireEvent.keyDown(textarea, { key: "Enter" });
    expect(onSubmit).not.toHaveBeenCalled();

    fireEvent.change(textarea, { target: { value: "Hej" } });
    expect(send.hasAttribute("disabled")).toBe(false);
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.keyDown(textarea, { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledTimes(1);
    fireEvent.click(send);
    expect(onSubmit).toHaveBeenCalledTimes(2);
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
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
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

  it("has no axe violations", async () => {
    const { container } = renderComposer({ initial: "Hej" });
    await expectNoAxeViolations(container);
  });
});
