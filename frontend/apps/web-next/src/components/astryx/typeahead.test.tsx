// @vitest-environment jsdom
import { createStaticSource } from "@astryxdesign/core/Typeahead";
import { screen } from "@testing-library/react";
import { createRef } from "react";
import { expect, it } from "vitest";
import { renderInApp } from "@/test/render";
import { Tokenizer } from "./tokenizer";
import { Typeahead } from "./typeahead";

const source = createStaticSource([{ id: "a", label: "Anna" }]);
const error = { type: "error" as const, message: "Välj en användare" };

it("marks the Typeahead's input invalid on an error and gives it the keyboard preset", () => {
  const ref = createRef<HTMLInputElement>();
  const { rerender } = renderInApp(
    <Typeahead
      ref={ref}
      label="Användare"
      searchSource={source}
      value={null}
      onChange={() => {}}
      status={error}
      inputMode="email"
      enterKeyHint="search"
      spellCheck={false}
    />
  );
  const input = screen.getByRole("combobox", { name: "Användare" });
  expect(ref.current).toBe(input);
  expect(input.getAttribute("aria-invalid")).toBe("true");
  expect(input.getAttribute("inputmode")).toBe("email");
  expect(input.getAttribute("enterkeyhint")).toBe("search");
  expect(input.getAttribute("spellcheck")).toBe("false");

  rerender(<Typeahead label="Användare" searchSource={source} value={null} onChange={() => {}} />);
  expect(screen.getByRole("combobox", { name: "Användare" }).hasAttribute("aria-invalid")).toBe(
    false
  );
});

it("marks the Tokenizer's input invalid on an error", () => {
  renderInApp(
    <Tokenizer
      label="Taggar"
      searchSource={source}
      value={[]}
      onChange={() => {}}
      status={error}
      inputMode="text"
    />
  );
  const input = screen.getByRole("combobox", { name: "Taggar" });
  expect(input.getAttribute("aria-invalid")).toBe("true");
  expect(input.getAttribute("inputmode")).toBe("text");
});
