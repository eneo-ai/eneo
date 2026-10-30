// @vitest-environment jsdom

import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { katexStore } from "@/components/ai-elements/math";
import type { Schema } from "@/lib/api/models";
import {
  assistantRichTextClipboardPayload,
  getPreferredAssistantCopyFormat,
  setPreferredAssistantCopyFormat
} from "./copy-assistant-answer";

type Settings = Schema<"SettingsPublic">;

// Warm, so each test's HTML is not slowed by loading KaTeX; math-load.test.tsx
// covers a copy made while KaTeX is still loading or cannot be loaded.
beforeAll(async () => {
  await katexStore.load();
});

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
    '**Answer** <inref id="aaaaaaaa"/> <script>alert(1)</script> [link](javascript:alert(1))',
    "Start $P$.\n\n\\[A = P(1+r)^n\\]\n\nPriser: $5 och $10.",
    "| År | Belopp |\n| --- | ---: |\n| 1 | 100 |\n\n```mermaid\ngraph LR\nA --> B\n```"
  ])("preserves the complete clipboard representation of %s", async (answer) => {
    const payload = await assistantRichTextClipboardPayload(answer);
    expect({ plainText: payload.plainText, html: await payload.html() }).toMatchSnapshot();
  });

  it.each([
    { property: "trust", value: true },
    { property: "processor", value: (value: unknown) => (value === false ? true : value) }
  ])(
    "ignores inherited KaTeX $property settings in copied formulas",
    async ({ property, value }) => {
      // Model pre-existing prototype pollution without leaking it to other tests.
      // Inherited setting processors must not turn our explicit trust:false into true.
      const previous = Object.getOwnPropertyDescriptor(Object.prototype, property);
      let payload: Awaited<ReturnType<typeof assistantRichTextClipboardPayload>>;
      let copied: string;
      try {
        Object.defineProperty(Object.prototype, property, {
          value,
          configurable: true,
          writable: true
        });
        payload = await assistantRichTextClipboardPayload(
          "Start $x^2$. $\\href{javascript:alert(1)}{x}$ " +
            "$\\includegraphics{https://example.test/tracking.png}$"
        );
        copied = await payload.html();
      } finally {
        if (previous) Object.defineProperty(Object.prototype, property, previous);
        else Reflect.deleteProperty(Object.prototype, property);
      }

      const html = document.createElement("div");
      html.innerHTML = copied;
      expect(html.querySelector("a, [href], img, mglyph")).toBeNull();
      expect(html.querySelector("math msup")).not.toBeNull();
      expect(payload.plainText).toContain("Start x^2.");
    }
  );

  it("renders markdown, strips inrefs, and removes unsafe html", async () => {
    const payload = await assistantRichTextClipboardPayload(
      '**Answer** <inref id="aaaaaaaa"/> <script>alert(1)</script> [link](javascript:alert(1))'
    );
    const copied = await payload.html();

    expect(copied).toContain("<strong>Answer</strong>");
    expect(copied).not.toContain("inref");
    expect(copied).not.toContain("script");
    expect(copied).not.toContain("javascript:");
    expect(payload.plainText).toContain("Answer");
  });

  it("copies formulas once as semantic MathML with a readable plain-text twin", async () => {
    const payload = await assistantRichTextClipboardPayload(
      "Start $P$.\n\n\\[A = P(1+r)^n\\]\n\nPriser: $5 och $10."
    );
    const html = document.createElement("div");
    html.innerHTML = await payload.html();
    expect(html.querySelectorAll("math")).toHaveLength(2);
    expect(html.querySelector(".katex-html")).toBeNull();
    expect(html.querySelector("style")).toBeNull();
    expect(payload.plainText).toContain("Start P.");
    expect(payload.plainText.match(/A = P\(1\+r\)\^n/g)).toHaveLength(1);
    expect(payload.plainText).toContain("$5 och $10");
  });

  it("keeps table structure, code and diagram source without interactive controls", async () => {
    const payload = await assistantRichTextClipboardPayload(
      "| År | Belopp |\n| --- | ---: |\n| 1 | 100 |\n\n" +
        "```python\nprice = '$5'\n```\n\n```mermaid\ngraph LR\nA --> B\n```"
    );
    const html = document.createElement("div");
    html.innerHTML = await payload.html();
    expect(html.querySelectorAll("th")).toHaveLength(2);
    expect(html.querySelectorAll("pre code")).toHaveLength(2);
    expect(html.querySelector("button")).toBeNull();
    expect(payload.plainText).toContain("price = '$5'");
    expect(payload.plainText).toContain("A --> B");
  });

  it("uses the same sanitization for event handlers and unsafe links as answers", async () => {
    const payload = await assistantRichTextClipboardPayload(
      '<img src="x" onerror="alert(1)"><iframe src="https://example.com"></iframe>' +
        '<a href="javascript:alert(1)">unsafe</a>'
    );
    expect(await payload.html()).not.toMatch(/onerror|<iframe|javascript:/i);
  });
});

describe("rich text while KaTeX cannot be loaded", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });
  function katexUnavailable() {
    vi.spyOn(katexStore, "load").mockResolvedValue();
    vi.spyOn(katexStore, "mathml").mockReturnValue(null);
  }

  it.each([
    ["money", "Kostar $5 och $10."],
    ["the word math", "The math department approved this."],
    ["a dollar in code", "```js\nconst price = '$5';\n```"]
  ])("still copies an answer with %s and no formula", async (_name, answer) => {
    katexUnavailable();
    const html = await (await assistantRichTextClipboardPayload(answer)).html();
    expect(html).not.toContain("<math");
    expect(html.length).toBeGreaterThan(0);
  });

  it("fails rather than copy a formula as code", async () => {
    katexUnavailable();
    await expect(
      (await assistantRichTextClipboardPayload("Låt $x^2$ vara talet.")).html()
    ).rejects.toThrow();
  });
});
