// @vitest-environment jsdom
import { fireEvent, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import { WidgetComposer } from "./widget-composer";

function composer() {
  const send = vi.fn();
  renderInApp(
    <WidgetComposer
      placeholder=""
      maxLength={1000}
      disabled={false}
      busy={false}
      value="En fråga"
      onChange={() => {}}
      onSend={send}
    />
  );
  return { input: screen.getByRole("textbox"), send };
}

it.each(["phone", "tablet-portrait"] as const)(
  "lets Return insert a line on %s without sending the question",
  (viewport) => {
    setViewport(viewport);
    const { input, send } = composer();
    expect(fireEvent.keyDown(input, { key: "Enter" })).toBe(true);
    expect(send).not.toHaveBeenCalled();
  }
);

it.each(["ctrlKey", "metaKey"] as const)("sends with %s+Return on touch", (modifier) => {
  setViewport("phone");
  const { input, send } = composer();
  expect(fireEvent.keyDown(input, { key: "Enter", [modifier]: true })).toBe(false);
  expect(send).toHaveBeenCalledWith("En fråga");
});

it("sends with Return on a pointer keyboard while Shift+Return inserts a line", () => {
  const { input, send } = composer();
  expect(fireEvent.keyDown(input, { key: "Enter", shiftKey: true })).toBe(true);
  expect(send).not.toHaveBeenCalled();
  expect(fireEvent.keyDown(input, { key: "Enter" })).toBe(false);
  expect(send).toHaveBeenCalledWith("En fråga");
});

it("never submits Return that confirms an input method word", () => {
  const { input, send } = composer();
  fireEvent.compositionStart(input);
  expect(fireEvent.keyDown(input, { key: "Enter" })).toBe(true);
  fireEvent.compositionEnd(input);
  // Safari may clear isComposing before dispatching its word-confirming Return.
  expect(fireEvent.keyDown(input, { key: "Enter", keyCode: 229 })).toBe(true);
  expect(send).not.toHaveBeenCalled();
});

it("keeps the send button available when Return adds lines on touch", () => {
  setViewport("phone");
  const { send } = composer();
  fireEvent.click(screen.getByRole("button", { name: "Skicka" }));
  expect(send).toHaveBeenCalledWith("En fråga");
});
