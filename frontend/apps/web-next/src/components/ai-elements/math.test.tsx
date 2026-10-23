// @vitest-environment jsdom
import { cleanup, screen, waitFor } from "@testing-library/react";
import { useMemo } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import katex from "katex";
import { cases } from "@eneo/markdown-math/cases.json";
import remarkMath from "remark-math";
import remarkParse from "remark-parse";
import { unified } from "unified";
import { resolveInrefs } from "@/lib/chat/inref";
import { renderInApp } from "@/test/render";
import { CitationSourcesProvider, citationComponents, remarkCitations } from "./citation";
import { mathPlugin } from "./math";
import { MessageResponse } from "./message";

afterEach(cleanup);

// What the reader sees: each KaTeX formula, display or inline, with the TeX it
// was typeset from (KaTeX keeps it in the MathML annotation).
function formulas(container: HTMLElement) {
  return [...container.querySelectorAll(".katex")].map((element) => ({
    display: element.closest(".katex-display") !== null,
    tex: normalize(element.querySelector('annotation[encoding="application/x-tex"]')?.textContent)
  }));
}

// Each run of whitespace, line breaks included, as one space.
function spaced(text: string | null) {
  return (text ?? "").replace(/\s+/g, " ");
}

function normalize(tex: string | null | undefined) {
  return (tex ?? "").replace(/\s+/g, " ").trim();
}

// As the chat renders an answer: its links are plain links, not Streamdown's
// link-safety buttons.
function Answer({ text }: { text: string }) {
  return (
    <CitationSourcesProvider value={[]} prefix="msg-1" onOpenSource={() => {}}>
      <MessageResponse components={citationComponents}>{text}</MessageResponse>
    </CitationSourcesProvider>
  );
}

function renderAnswer(text: string) {
  return renderInApp(<Answer text={text} />);
}

// The same cases as the web app's Math.svelte.test.ts, from @eneo/markdown-math.
describe("Math in answers", () => {
  for (const c of cases) {
    it(c.name, async () => {
      const { container } = renderAnswer(c.input);
      const expected = c.math.map((formula) => ({
        display: formula.display,
        tex: normalize(formula.tex)
      }));
      await waitFor(() => {
        expect(formulas(container)).toEqual(expected);
        for (const text of c.literal ?? []) {
          expect(spaced(container.textContent)).toContain(spaced(text));
        }
      });
      if (c.href) expect(container.querySelector("a")?.getAttribute("href")).toBe(c.href);
    });
  }

  // Streamdown re-renders the block that is still growing; a finished block,
  // and every formula in it, is left alone.
  it("does not typeset a finished block again while the answer streams", async () => {
    const typeset = vi.spyOn(katex, "renderToString");
    const first = "Låt $x^2$ vara talet.\n\n";
    const { container, rerender } = renderAnswer(`${first}Och`);
    await waitFor(() => expect(container.querySelector(".katex")).not.toBeNull());
    const formula = container.querySelector(".katex");
    const calls = typeset.mock.calls.length;

    rerender(<Answer text={`${first}Och mer`} />);
    rerender(<Answer text={`${first}Och mer text`} />);
    await waitFor(() => expect(container.textContent).toContain("mer text"));
    expect(container.querySelector(".katex")).toBe(formula);
    expect(typeset).toHaveBeenCalledTimes(calls);
    typeset.mockRestore();
  });

  it("shows a formula KaTeX cannot handle as written, and keeps the answer", async () => {
    const deep = "{".repeat(20000) + "x" + "}".repeat(20000);
    const { container } = renderAnswer(`Före $${deep}$ efter`);
    await waitFor(() => expect(container.querySelector(".katex-error")).not.toBeNull());
    expect(container.querySelector(".katex-error")?.textContent).toContain("{{{x}}}");
    expect(container.textContent).toContain("efter");
  });

  // An unfinished fence is a paragraph from the start, so the chat's citation
  // plugin, which runs before math, still turns its markers into sources.
  it("keeps a citation after an unfinished formula a source", async () => {
    const sources = [
      { title: "Upphandlingspolicy 2024", url: "https://intranat.kommun.se/policy" }
    ];
    function Cited({ text }: { text: string }) {
      const remarkPlugins = useMemo(() => [remarkCitations(sources.length, "msg-1")], []);
      return (
        <CitationSourcesProvider value={sources} prefix="msg-1" onOpenSource={() => {}}>
          <MessageResponse remarkPlugins={remarkPlugins} components={citationComponents}>
            {resolveInrefs(text, ["a5477f85-1111"])}
          </MessageResponse>
        </CitationSourcesProvider>
      );
    }
    // Never closed, and closed by a line too far in to count as a closing fence.
    for (const text of [
      '$$\nSvar enligt policyn<inref id="a5477f85"/>',
      '$$\nx\n    $$\n\nSvar enligt policyn<inref id="a5477f85"/>'
    ]) {
      const { container, unmount } = renderInApp(<Cited text={text} />);
      expect(
        await screen.findByRole("button", { name: "Källa 1: Upphandlingspolicy 2024" })
      ).toBeTruthy();
      expect(container.textContent).toContain("Svar enligt policyn");
      expect(container.textContent).not.toMatch(/[\uE000\uE001]/);
      unmount();
    }
  });

  it("renders untrusted TeX without links, images or unbounded sizes", async () => {
    const { container } = renderAnswer(
      "$\\href{javascript:alert(1)}{x}$ $\\url{javascript:alert(1)}$ " +
        "$\\includegraphics{https://example.test/a.png}$ $\\htmlClass{x}{y}$\n\n" +
        "$$\\rule{100000em}{100000em}$$"
    );
    await waitFor(() => expect(container.querySelector(".katex-display")).not.toBeNull());
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector(".x")).toBeNull();
    // jsdom has no layout: the rule's size is in its inline style, capped at maxSize.
    const rule = container.querySelector(".katex-display .katex-rule") as HTMLElement;
    expect(rule.getAttribute("style")).not.toContain("100000");
  });

  it("shows invalid TeX as an error instead of breaking the answer", async () => {
    const { container } = renderAnswer("Före $\\frac{a$ efter");
    await waitFor(() => expect(container.querySelector(".katex-error")).not.toBeNull());
    expect(container.textContent).toContain("efter");
  });
});

describe("math parsing time", () => {
  const remarkMathOnly = unified()
    .use(remarkParse)
    .use(remarkMath, { singleDollarTextMath: false });
  const llmMath = unified().use(remarkParse).use([mathPlugin.remarkPlugin]);

  function fastest(processor: typeof llmMath, source: string) {
    let best = Infinity;
    for (let run = 0; run < 3; run++) {
      const started = performance.now();
      processor.runSync(processor.parse(source), source);
      best = Math.min(best, performance.now() - started);
    }
    return best;
  }

  // Measured against remark-math alone, so a slow runner does not fail the
  // test: a search that starts over at each token is tens to hundreds of
  // times slower at this size. The same answers as the web app's lexer test.
  const answers = {
    "many paragraphs": "Klicka på **Arkiv** och _Alternativ_ <b>nu</b>!\n\n".repeat(4000),
    "many inline tokens without math": "a_ b! c< ".repeat(4000),
    "many empty fences": "$$\n$$\n\n".repeat(4000),
    "many unclosed openers": "\\(a \\[b ".repeat(4000)
  };

  // The limit only stops a hang; the check is the ratio, not the time.
  for (const [name, source] of Object.entries(answers)) {
    it(`grows with the answer, as remark-math does: ${name}`, { timeout: 30_000 }, () => {
      expect(fastest(llmMath, source)).toBeLessThan(5 * fastest(remarkMathOnly, source) + 50);
    });
  }

  it("reads a long run of unclosed openers as text", () => {
    const source = "\\(a ".repeat(20000);
    const tree = llmMath.runSync(llmMath.parse(source), source);
    expect(JSON.stringify(tree)).not.toContain("inlineMath");
  });
});
