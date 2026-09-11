import { render } from "vitest-browser-svelte";
import { describe, expect, it } from "vitest";
import { Markdown } from "@eneo/ui";

const fence = (lang: string, code: string) => `Exempel:\n\n\`\`\`${lang}\n${code}\n\`\`\`\n`;

describe("Markdown code blocks", () => {
  it("highlights a fenced language as that language", () => {
    const { container } = render(Markdown, {
      source: fence("json", '{ "namn": "Anna", "aktiv": true }')
    });
    // JSON keys are attributes; detection used to read this block as JavaScript.
    expect(container.querySelector("code.hljs .hljs-attr")?.textContent).toBe('"namn"');
  });

  it("falls back to detection for an unknown or missing language", () => {
    const { container } = render(Markdown, {
      source:
        fence("brainfuck", "def hej():\n    return 1") + fence("", "const x = 1;\nconsole.log(x);")
    });
    const blocks = container.querySelectorAll("code.hljs");
    expect(blocks).toHaveLength(2);
    expect(blocks[0].querySelector(".hljs-keyword")?.textContent).toBe("def");
    expect(blocks[1].querySelector(".hljs-keyword")?.textContent).toBe("const");
  });

  it("tolerates a block that is still streaming", () => {
    const { container } = render(Markdown, {
      source: 'Kod:\n\n```python\nprint("hej'
    });
    expect(container.querySelector("code.hljs")?.textContent).toContain('print("hej');
  });
});
