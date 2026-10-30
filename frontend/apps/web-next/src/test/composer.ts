import { fireEvent, screen } from "@testing-library/react";

/** The chat composer's text field, by its persistent name ("Fråga …"). */
export function chatComposer(name: RegExp | string = /^Fråga /): HTMLElement {
  return screen.getByRole("textbox", { name });
}

/** Replaces the field's text, as a person who selected everything and typed would. */
export function typeIntoComposer(field: HTMLElement, text: string) {
  if (field instanceof HTMLTextAreaElement) {
    fireEvent.change(field, { target: { value: text } });
    return;
  }
  field.textContent = text;
  fireEvent.input(field);
}

/** The text in the field. */
export function composerValue(field: HTMLElement): string {
  return field instanceof HTMLTextAreaElement ? field.value : (field.textContent ?? "");
}
