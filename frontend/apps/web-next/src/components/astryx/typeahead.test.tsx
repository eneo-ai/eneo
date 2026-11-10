// @vitest-environment jsdom
import { createStaticSource } from "@astryxdesign/core/Typeahead";
import { screen } from "@testing-library/react";
import { createRef } from "react";
import { expect, it } from "vitest";
import { renderInApp } from "@/test/render";
import { Tokenizer } from "./tokenizer";
import { Typeahead } from "./typeahead";

const source = createStaticSource([{ id: "a", label: "Anna" }]);

it("gives the Typeahead's input the keyboard preset", () => {
  const ref = createRef<HTMLInputElement>();
  renderInApp(
    <Typeahead
      ref={ref}
      label="Användare"
      searchSource={source}
      value={null}
      onChange={() => {}}
      inputMode="email"
      enterKeyHint="search"
      spellCheck={false}
    />
  );
  const input = screen.getByRole("combobox", { name: "Användare" });
  expect(ref.current).toBe(input);
  expect(input.getAttribute("inputmode")).toBe("email");
  expect(input.getAttribute("enterkeyhint")).toBe("search");
  expect(input.getAttribute("spellcheck")).toBe("false");
});

it("gives the Tokenizer's input the keyboard preset", () => {
  renderInApp(
    <Tokenizer
      label="Taggar"
      searchSource={source}
      value={[]}
      onChange={() => {}}
      inputMode="text"
    />
  );
  expect(screen.getByRole("combobox", { name: "Taggar" }).getAttribute("inputmode")).toBe("text");
});
