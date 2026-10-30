// @vitest-environment jsdom
import { screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { renderInApp } from "@/test/render";
import { KEYBOARD } from "./keyboard-hints";
import { TextInput } from "./text-input";

const attributes = (field: HTMLElement) => ({
  inputmode: field.getAttribute("inputmode"),
  enterkeyhint: field.getAttribute("enterkeyhint"),
  autocapitalize: field.getAttribute("autocapitalize"),
  autocorrect: field.getAttribute("autocorrect"),
  spellcheck: field.getAttribute("spellcheck")
});

it("gives a search field a search key and no capital, auto-correction or spell-check marks", () => {
  renderInApp(
    <TextInput label="Filtrera ytor" value="" onChange={() => {}} {...KEYBOARD.search} />
  );
  expect(attributes(screen.getByLabelText("Filtrera ytor"))).toEqual({
    inputmode: "search",
    enterkeyhint: "search",
    autocapitalize: "none",
    autocorrect: "off",
    spellcheck: "false"
  });
});

it("gives an address field the keyboard with @ and an identifier field neither", () => {
  renderInApp(
    <>
      <TextInput label="E-post" value="" onChange={() => {}} {...KEYBOARD.email} />
      <TextInput label="Användarnamn" value="" onChange={() => {}} {...KEYBOARD.identifier} />
    </>
  );
  expect(attributes(screen.getByLabelText("E-post"))).toMatchObject({
    inputmode: "email",
    autocapitalize: "none",
    spellcheck: "false"
  });
  expect(attributes(screen.getByLabelText("Användarnamn"))).toMatchObject({
    inputmode: null,
    enterkeyhint: null,
    autocapitalize: "none",
    spellcheck: "false"
  });
});
