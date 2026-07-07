// @vitest-environment jsdom

import { describe, expect, it } from "vitest";
import type { Schema } from "@/lib/api/models";
import {
  assistantRichTextClipboardPayload,
  getPreferredAssistantCopyFormat,
  setPreferredAssistantCopyFormat
} from "./copy-assistant-answer";

type Settings = Schema<"SettingsPublic">;

describe("getPreferredAssistantCopyFormat", () => {
  it("falls back to markdown for missing or invalid settings", () => {
    expect(getPreferredAssistantCopyFormat(null)).toBe("markdown");
    expect(getPreferredAssistantCopyFormat({ chatbot_widget: {} })).toBe("markdown");
    expect(
      getPreferredAssistantCopyFormat({
        chatbot_widget: { preferred_text_format: "html" }
      })
    ).toBe("markdown");
  });

  it("reads and writes the chatbot widget setting without dropping sibling keys", () => {
    const settings: Settings = {
      chatbot_widget: {
        preferred_text_format: "markdown",
        theme: "dark"
      }
    };

    expect(getPreferredAssistantCopyFormat(settings)).toBe("markdown");
    expect(setPreferredAssistantCopyFormat(settings, "richtext")).toEqual({
      preferred_text_format: "richtext",
      theme: "dark"
    });
  });
});

describe("assistantRichTextClipboardPayload", () => {
  it("renders markdown, strips inrefs, and removes unsafe html", () => {
    const payload = assistantRichTextClipboardPayload(
      '**Answer** <inref id="aaaaaaaa"/> <script>alert(1)</script> [link](javascript:alert(1))'
    );

    expect(payload.html).toContain("<strong>Answer</strong>");
    expect(payload.html).not.toContain("inref");
    expect(payload.html).not.toContain("script");
    expect(payload.html).not.toContain("javascript:");
    expect(payload.plainText).toContain("Answer");
  });
});
