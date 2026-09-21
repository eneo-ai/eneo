import { describe, expect, it } from "vitest";
import { isGroupLocked, lockedTextFields } from "./templateLocks";

describe("template locks", () => {
  it("maps lock groups onto the text fields the editor must freeze", () => {
    expect([...lockedTextFields(null)]).toEqual([]);
    expect([...lockedTextFields({ locked_groups: ["appearance", "language"] })]).toEqual([]);
    expect([...lockedTextFields({ locked_groups: ["legal_texts"] })]).toEqual([
      "subtitle",
      "footer_text",
      "footer_link_url",
      "footer_link_label"
    ]);
    expect([...lockedTextFields({ locked_groups: ["wording", "legal_texts"] })]).toEqual([
      "subtitle",
      "footer_text",
      "footer_link_url",
      "footer_link_label",
      "title",
      "welcome",
      "placeholder"
    ]);
  });

  it("answers whole-group locks", () => {
    expect(isGroupLocked({ locked_groups: ["appearance"] }, "appearance")).toBe(true);
    expect(isGroupLocked({ locked_groups: ["appearance"] }, "language")).toBe(false);
    expect(isGroupLocked(null, "appearance")).toBe(false);
  });
});
