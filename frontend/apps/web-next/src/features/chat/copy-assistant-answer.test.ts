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
  it.each([
    { property: "trust", value: true },
    { property: "processor", value: (value: unknown) => (value === false ? true : value) }
  ])("ignores inherited KaTeX $property settings in copied formulas", ({ property, value }) => {
    // Model pre-existing prototype pollution without leaking it to other tests.
    // Inherited setting processors must not turn our explicit trust:false into true.
    const previous = Object.getOwnPropertyDescriptor(Object.prototype, property);
    let payload: ReturnType<typeof assistantRichTextClipboardPayload>;
    try {
      Object.defineProperty(Object.prototype, property, {
        value,
        configurable: true,
        writable: true
      });
      payload = assistantRichTextClipboardPayload(
        "Start $x^2$. $\\href{javascript:alert(1)}{x}$ " +
          "$\\includegraphics{https://example.test/tracking.png}$"
      );
    } finally {
      if (previous) Object.defineProperty(Object.prototype, property, previous);
      else Reflect.deleteProperty(Object.prototype, property);
    }

    const html = document.createElement("div");
    html.innerHTML = payload.html;
    expect(html.querySelector("a, [href], img, mglyph")).toBeNull();
    expect(html.querySelector("math msup")).not.toBeNull();
    expect(payload.plainText).toContain("Start x^2.");
  });

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

  it("copies formulas once as semantic MathML with a readable plain-text twin", () => {
    const payload = assistantRichTextClipboardPayload(
      "Start $P$.\n\n\\[A = P(1+r)^n\\]\n\nPriser: $5 och $10."
    );
    const html = document.createElement("div");
    html.innerHTML = payload.html;
    expect(html.querySelectorAll("math")).toHaveLength(2);
    expect(html.querySelector(".katex-html")).toBeNull();
    expect(html.querySelector("style")).toBeNull();
    expect(payload.plainText).toContain("Start P.");
    expect(payload.plainText.match(/A = P\(1\+r\)\^n/g)).toHaveLength(1);
    expect(payload.plainText).toContain("$5 och $10");
  });

  it("keeps table structure, code and diagram source without interactive controls", () => {
    const payload = assistantRichTextClipboardPayload(
      "| År | Belopp |\n| --- | ---: |\n| 1 | 100 |\n\n" +
        "```python\nprice = '$5'\n```\n\n```mermaid\ngraph LR\nA --> B\n```"
    );
    const html = document.createElement("div");
    html.innerHTML = payload.html;
    expect(html.querySelectorAll("th")).toHaveLength(2);
    expect(html.querySelectorAll("pre code")).toHaveLength(2);
    expect(html.querySelector("button")).toBeNull();
    expect(payload.plainText).toContain("price = '$5'");
    expect(payload.plainText).toContain("A --> B");
  });

  it("uses the same sanitization for event handlers and unsafe links as answers", () => {
    const payload = assistantRichTextClipboardPayload(
      '<img src="x" onerror="alert(1)"><iframe src="https://example.com"></iframe>' +
        '<a href="javascript:alert(1)">unsafe</a>'
    );
    expect(payload.html).not.toMatch(/onerror|<iframe|javascript:/i);
  });
});
