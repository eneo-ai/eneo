/* eslint-disable eneo/no-raw-color -- fixtures use literal widget colours */
import type { WidgetTemplate } from "@eneo/eneo-js";
import { describe, expect, it } from "vitest";
import {
  isGroupLocked,
  lockedTextFields,
  publicationSummary,
  templateRelease
} from "./templateLocks";

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

function template(overrides: Partial<WidgetTemplate> = {}): WidgetTemplate {
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
  } as unknown as WidgetTemplate;
}

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

  it("links widgets to the published release, not the draft", () => {
    const draft = template({ theme: { primary_color: "#654321", radius: 4 } });
    expect(templateRelease(draft).theme).toEqual({ primary_color: "#1F4E79", radius: 12 });
    expect(templateRelease(template({ published: null, published_at: null })).theme).toEqual({
      primary_color: "#1F4E79",
      radius: 12
    });
  });

  it("reports nothing to write when the draft only differs outside the locks", () => {
    const summary = publicationSummary(
      template({ texts: { ...texts, title: "Fråga Sundsvall" }, description: "Ny text" })
    );
    expect(summary).toEqual({
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
    expect(summary).toEqual({
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
    expect(summary.written).toEqual(["language"]);
  });

  it("writes every locked part of a first publication", () => {
    const summary = publicationSummary(template({ published: null, published_at: null }));
    expect(summary.written).toEqual(["appearance", "language"]);
    expect(summary.newlyLocked).toEqual(["appearance", "language"]);
    expect(summary.changedUnlocked).toEqual(["legal_texts", "wording"]);
  });
});
