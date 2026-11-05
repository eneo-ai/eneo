// @vitest-environment jsdom
import { fireEvent, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { KEYBOARD } from "./keyboard-hints";
import { TextInput } from "./text-input";

function Field({ error, help }: { error?: string; help?: string }) {
  return (
    <>
      <p id="old-help">Kraven</p>
      <p id="new-help">Nya kraven</p>
      <TextInput
        label="Nytt lösenord"
        description="Minst 12 tecken"
        value=""
        onChange={() => {}}
        aria-describedby={help}
        status={error ? { type: "error", message: error } : undefined}
      />
    </>
  );
}

const describedBy = () =>
  (screen.getByLabelText(/^Nytt lösenord/).getAttribute("aria-describedby") ?? "")
    .split(" ")
    .map((id) => document.getElementById(id)?.textContent);

it("is described by the caller's ids and Astryx's own description and status, never stale ones", () => {
  const { rerender } = renderInApp(<Field help="old-help" />);
  expect(describedBy()).toEqual(["Kraven", "Minst 12 tecken"]);

  rerender(<Field help="old-help" error="Använd minst 12 tecken" />);
  expect(describedBy()).toEqual(["Kraven", "Minst 12 tecken", "Använd minst 12 tecken"]);

  rerender(<Field help="new-help" />);
  expect(describedBy()).toEqual(["Nya kraven", "Minst 12 tecken"]);

  rerender(<Field />);
  expect(describedBy()).toEqual(["Minst 12 tecken"]);
});

it("lets the search key put the keyboard away after running Enter", () => {
  const onEnter = vi.fn();
  renderInApp(
    <TextInput
      label="Filtrera"
      value=""
      onChange={() => {}}
      onEnter={onEnter}
      {...KEYBOARD.search}
    />
  );
  const input = screen.getByRole("textbox", { name: "Filtrera" });
  input.focus();
  fireEvent.keyDown(input, { key: "Enter" });
  expect(onEnter).toHaveBeenCalledTimes(1);
  expect(document.activeElement).not.toBe(input);
});
