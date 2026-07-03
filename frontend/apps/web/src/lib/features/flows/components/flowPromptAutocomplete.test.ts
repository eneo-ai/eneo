import { describe, it, expect } from "vitest";
import { findOpenTokenStart, findAtTriggerStart } from "./flowPromptAutocomplete";

describe("findOpenTokenStart", () => {
  it("returns the index of an open {{ at the cursor", () => {
    expect(findOpenTokenStart("hej {{", 6)).toBe(4);
  });

  it("returns null once the token is closed", () => {
    expect(findOpenTokenStart("hej {{namn}}", 12)).toBeNull();
  });

  it("returns null when there is no open brace before the cursor", () => {
    expect(findOpenTokenStart("hej namn", 8)).toBeNull();
  });

  it("only considers text before the cursor", () => {
    expect(findOpenTokenStart("a {{b", 1)).toBeNull();
  });
});

describe("findAtTriggerStart", () => {
  it("triggers on @ at the very start", () => {
    expect(findAtTriggerStart("@", 1)).toBe(0);
  });

  it("triggers on @ after whitespace", () => {
    expect(findAtTriggerStart("hej @", 5)).toBe(4);
  });

  it("triggers on @ after an opening bracket", () => {
    expect(findAtTriggerStart("(@", 2)).toBe(1);
  });

  it("does not trigger on @ in the middle of a word", () => {
    expect(findAtTriggerStart("mail@x", 6)).toBeNull();
  });

  it("does not trigger once a space follows the @", () => {
    expect(findAtTriggerStart("@namn ", 6)).toBeNull();
  });

  it("does not trigger while inside an open {{ token", () => {
    expect(findAtTriggerStart("{{@", 3)).toBeNull();
  });
});
