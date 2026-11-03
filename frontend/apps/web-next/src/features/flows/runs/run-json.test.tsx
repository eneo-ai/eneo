// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { renderInApp } from "@/test/render";
import { JsonValue } from "./run-json";

afterEach(cleanup);

const id = "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08";

// jsdom lays nothing out: these pin the classes that keep a value within its place.
describe("JsonValue", () => {
  it("lets no value or name widen the page", () => {
    const { container } = renderInApp(
      <JsonValue value={{ "ett mycket långt fältnamn utan slut": id, lista: [id] }} />
    );
    const list = container.querySelector("dl")!;
    // A bare `1fr` starts at its content's width; `minmax(0,1fr)` at nothing.
    expect(list.className).toContain("sm:grid-cols-[minmax(8rem,max-content)_minmax(0,1fr)]");
    expect(list.className).toContain("min-w-0");
    for (const name of container.querySelectorAll("dt")) {
      expect(name.className).toContain("[overflow-wrap:anywhere]");
      expect(name.className).toContain("max-w-60");
    }
    for (const value of container.querySelectorAll("dd")) {
      expect(value.className).toContain("min-w-0");
    }
    // `anywhere` lowers the width a long word asks for; `break-word` does not.
    for (const text of screen.getAllByText(id)) {
      expect(text.className).toContain("[overflow-wrap:anywhere]");
    }
  });

  it("shows a value nested deeper than three levels as a JSON block that wraps", () => {
    const { container } = renderInApp(<JsonValue value={{ a: { b: { c: { d: id } } } }} />);
    const block = container.querySelector("[data-json-block]");
    expect(block).toBeTruthy();
    expect(block?.textContent).toContain(`"d": "${id}"`);
    // Not a `<pre>` that scrolls sideways.
    expect(container.querySelector("pre.overflow-x-auto")).toBeNull();
  });
});
