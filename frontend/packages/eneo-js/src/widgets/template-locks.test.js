import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  isGroupLocked,
  lockedTextFields,
  publicationSummary,
  templateRelease
} from "./template-locks.js";
const texts = {
  title: "Fråga oss",
  welcome: "Hej",
  placeholder: "Skriv",
  subtitle: "AI",
  footer_text: "",
  footer_link_url: "",
  footer_link_label: "",
  suggested_questions: []
};
function template(overrides = {}) {
  return {
    id: "t1",
    name: "Kommunblå",
    description: "",
    texts,
    theme: { primary_color: "#1F4E79", radius: 12 },
    language: "sv",
    is_default: false,
    locked_groups: ["appearance", "language"],
    linked_widgets: 2,
    published_at: "2026-09-21T10:00:00Z",
    published_by_user_id: null,
    published: {
      texts,
      theme: { primary_color: "#1F4E79", radius: 12 },
      language: "sv",
      locked_groups: ["appearance", "language"]
    },
    has_unpublished_changes: false,
    created_at: "2026-09-21T10:00:00Z",
    updated_at: "2026-09-21T10:00:00Z",
    ...overrides
  };
}
describe("template locks", () => {
  it("maps lock groups onto the text fields the editor must freeze", () => {
    assert.deepStrictEqual([...lockedTextFields(null)], []);
    assert.deepStrictEqual(
      [...lockedTextFields({ locked_groups: ["appearance", "language"] })],
      []
    );
    assert.deepStrictEqual(
      [...lockedTextFields({ locked_groups: ["legal_texts"] })],
      ["subtitle", "footer_text", "footer_link_url", "footer_link_label"]
    );
    assert.deepStrictEqual(
      [...lockedTextFields({ locked_groups: ["wording", "legal_texts"] })],
      [
        "subtitle",
        "footer_text",
        "footer_link_url",
        "footer_link_label",
        "title",
        "welcome",
        "placeholder"
      ]
    );
  });
  it("answers whole-group locks", () => {
    assert.deepStrictEqual(isGroupLocked({ locked_groups: ["appearance"] }, "appearance"), true);
    assert.deepStrictEqual(isGroupLocked({ locked_groups: ["appearance"] }, "language"), false);
    assert.deepStrictEqual(isGroupLocked(null, "appearance"), false);
  });
  it("links widgets to the published release, not the draft", () => {
    const draft = template({ theme: { primary_color: "#654321", radius: 4 } });
    assert.deepStrictEqual(templateRelease(draft).theme, { primary_color: "#1F4E79", radius: 12 });
    assert.deepStrictEqual(
      templateRelease(template({ published: null, published_at: null })).theme,
      {
        primary_color: "#1F4E79",
        radius: 12
      }
    );
  });
  it("reports nothing to write when the draft only differs outside the locks", () => {
    const summary = publicationSummary(
      template({ texts: { ...texts, title: "Fråga Sundsvall" }, description: "Ny text" })
    );
    assert.deepStrictEqual(summary, {
      written: [],
      newlyLocked: [],
      released: [],
      changedUnlocked: ["wording"]
    });
  });
  it("reports changed locked parts and lock changes", () => {
    const summary = publicationSummary(
      template({
        theme: { radius: 12, primary_color: "#654321" },
        texts: { ...texts, subtitle: "AI-assistent" },
        locked_groups: ["appearance", "legal_texts"]
      })
    );
    assert.deepStrictEqual(summary, {
      written: ["appearance", "legal_texts"],
      newlyLocked: ["legal_texts"],
      released: ["language"],
      changedUnlocked: []
    });
  });
  it("treats an unchanged locked part as already on the followers", () => {
    const summary = publicationSummary(
      template({ theme: { radius: 12, primary_color: "#1F4E79" }, language: "en" })
    );
    assert.deepStrictEqual(summary.written, ["language"]);
  });
  it("reports a changed locked persona without reporting other unchanged groups", () => {
    const published = template().published;
    published.persona = { name: "Old name", avatar_url: null };
    published.locked_groups = ["persona"];
    const summary = publicationSummary(
      template({
        persona: { name: "New name", avatar_url: null },
        locked_groups: ["persona"],
        published
      })
    );
    assert.deepEqual(summary, {
      written: ["persona"],
      newlyLocked: [],
      released: [],
      changedUnlocked: []
    });
  });
  it("writes every locked part of a first publication", () => {
    const summary = publicationSummary(template({ published: null, published_at: null }));
    assert.deepStrictEqual(summary.written, ["appearance", "language"]);
    assert.deepStrictEqual(summary.newlyLocked, ["appearance", "language"]);
    assert.deepStrictEqual(summary.changedUnlocked, ["legal_texts", "persona", "wording"]);
  });
});
