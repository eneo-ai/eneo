import { describe, expect, it } from "vitest";
import {
  isGroupLocked,
  lockedTextFields,
  publicationSummary,
  templateRelease,
  type WidgetTemplate
} from "./template-locks";

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
});

describe("publicationSummary", () => {
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
  const persona = { name: "", avatar_icon_id: null, avatar_in_launcher: false };
  const release = {
    texts,
    theme: { radius: 12, primary_color: "#1F4E79" },
    persona,
    language: "sv" as const,
    locked_groups: ["appearance", "language"] as WidgetTemplate["locked_groups"]
  };
  function template(overrides: Partial<WidgetTemplate> = {}): WidgetTemplate {
    return {
      id: "t1",
      name: "Kommunmallen",
      description: "",
      ...release,
      is_default: false,
      linked_widgets: 2,
      published_at: "2026-09-21T10:00:00Z",
      published: release,
      has_unpublished_changes: true,
      created_at: "2026-09-21T10:00:00Z",
      updated_at: "2026-09-21T10:00:00Z",
      ...overrides
    } as WidgetTemplate;
  }

  it("reports a changed unlocked part as kept by the followers", () => {
    expect(
      publicationSummary(
        template({ texts: { ...texts, title: "Fråga Sundsvall" }, description: "Ny text" })
      )
    ).toEqual({ written: [], newlyLocked: [], released: [], changedUnlocked: ["wording"] });
  });

  it("reports changed locked parts and lock changes", () => {
    expect(
      publicationSummary(
        template({
          theme: { radius: 12, primary_color: "#654321" },
          texts: { ...texts, subtitle: "AI-assistent" },
          locked_groups: ["appearance", "legal_texts"]
        })
      )
    ).toEqual({
      written: ["appearance", "legal_texts"],
      newlyLocked: ["legal_texts"],
      released: ["language"],
      changedUnlocked: []
    });
  });

  it("ignores key order when comparing a locked part", () => {
    const summary = publicationSummary(
      template({ theme: { primary_color: "#1F4E79", radius: 12 }, language: "en" })
    );
    expect(summary.written).toEqual(["language"]);
  });

  it("writes every locked part of a first publication", () => {
    const summary = publicationSummary(template({ published: null, published_at: null }));
    expect(summary.written).toEqual(["appearance", "language"]);
    expect(summary.newlyLocked).toEqual(["appearance", "language"]);
    expect(summary.changedUnlocked).toEqual(["legal_texts", "persona", "wording"]);
  });
});
