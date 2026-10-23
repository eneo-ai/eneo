/**
 * Test-only: drives the chat composer's text field, an Astryx
 * ChatComposerInput (a contenteditable element, not a textarea). Typing is
 * an `input` event after the text is put in the element, as a browser does;
 * the field's value is its serialized text.
 */
import { fireEvent, screen } from "@testing-library/react";

/** The chat composer's text field, by its persistent name ("Meddelande till …"). */
export function chatComposer(name: RegExp | string = /Meddelande till/): HTMLElement {
  return screen.getByRole("textbox", { name });
}

/** Replaces the field's text, as a person who selected everything and typed would. */
export function typeIntoComposer(field: HTMLElement, text: string) {
  field.textContent = text;
  fireEvent.input(field);
}

/** The text in the field. */
export function composerValue(field: HTMLElement): string {
  return field.textContent ?? "";
}
