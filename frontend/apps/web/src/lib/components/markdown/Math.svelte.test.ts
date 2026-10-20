import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import katex from "katex";
import { cases } from "@eneo/markdown-math/cases.json";
import { Markdown } from "./index.js";

// What the reader sees: each KaTeX formula, display or inline, with the TeX it
// was typeset from (KaTeX keeps it in the MathML annotation).
function formulas(container: HTMLElement) {
  return [...container.querySelectorAll(".katex")].map((element) => ({
    display: element.closest(".katex-display") !== null,
    tex: normalize(element.querySelector('annotation[encoding="application/x-tex"]')?.textContent)
  }));
}

// The text as read, a line break included, with each run of whitespace as one space.
function readable(container: HTMLElement) {
  const copy = container.cloneNode(true) as HTMLElement;
  for (const br of copy.querySelectorAll("br")) br.replaceWith("\n");
  return spaced(copy.textContent);
}

function spaced(text: string | null) {
  return (text ?? "").replace(/\s+/g, " ");
}

function normalize(tex: string | null | undefined) {
  return (tex ?? "").replace(/\s+/g, " ").trim();
}

describe("Math in answers", () => {
  // Runs first: KaTeX loads on the first formula, so the cases below render
  // synchronously and an empty result means "no math", not "not loaded yet".
  it("shows the formula as written until KaTeX has loaded", async () => {
    const { container } = render(Markdown, { source: "Pilen $\\rightarrow$ här" });
    expect(container.textContent).toContain("$\\rightarrow$");
    await expect.poll(() => container.querySelector(".katex")).not.toBeNull();
    expect(container.textContent).not.toContain("$\\rightarrow$");
  });

  for (const c of cases) {
    it(c.name, () => {
      const { container } = render(Markdown, { source: c.input });
      expect(formulas(container)).toEqual(
        c.math.map((formula) => ({ display: formula.display, tex: normalize(formula.tex) }))
      );
      expect(container.querySelectorAll("[data-math]")).toHaveLength(c.math.length);
      for (const text of c.literal ?? []) expect(readable(container)).toContain(spaced(text));
      if (c.href) expect(container.querySelector("a")?.getAttribute("href")).toBe(c.href);
    });
  }

  it("keeps display math out of the paragraph markup", () => {
    const { container } = render(Markdown, { source: "Före\n\n\\[x\\]\n\nefter \\[y\\] slut" });
    expect(container.querySelector("p [data-math='block']")).toBeNull();
    expect(container.querySelector("[data-math='block'] .katex-display")).not.toBeNull();
    expect(container.querySelector("p [data-math='inline'] .katex")).not.toBeNull();
  });

  it("strikes through code with a dollar without pairing it with another code span", () => {
    const { container } = render(Markdown, { source: "~~`$x`~~ + `y$`" });
    expect(container.querySelector("del code")?.textContent).toBe("$x");
    expect(container.querySelectorAll("code")).toHaveLength(2);
    expect(container.querySelector("[data-math]")).toBeNull();
    expect(container.textContent).not.toContain("~~");
  });

  it("does not typeset a finished formula again while the answer streams", async () => {
    const typeset = vi.spyOn(katex, "renderToString");
    const { container, rerender } = render(Markdown, { source: "Låt $x^2$ vara" });
    const formula = container.querySelector(".katex");
    expect(typeset).toHaveBeenCalledTimes(1);

    await rerender({ source: "Låt $x^2$ vara talet och $y" });
    expect(container.querySelector(".katex")).toBe(formula);
    expect(container.textContent).toContain("$y");
    expect(typeset).toHaveBeenCalledTimes(1);
    typeset.mockRestore();
  });

  it("shows a formula KaTeX cannot handle as written, and keeps the answer", () => {
    const deep = "{".repeat(20000) + "x" + "}".repeat(20000);
    const { container } = render(Markdown, { source: `Före $${deep}$ efter` });
    expect(container.querySelector(".katex")).toBeNull();
    expect(container.querySelector("[data-math]")?.textContent).toContain("{{{x}}}");
    expect(container.textContent).toContain("efter");
  });

  it("renders untrusted TeX without links, images or unbounded sizes", () => {
    const { container } = render(Markdown, {
      source:
        "$\\href{javascript:alert(1)}{x}$ $\\url{javascript:alert(1)}$ " +
        "$\\includegraphics{https://example.test/a.png}$ $\\htmlClass{x}{y}$\n\n" +
        "$$\\rule{100000em}{100000em}$$"
    });
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector(".x")).toBeNull();
    const display = container.querySelector(".katex-display") as HTMLElement;
    expect(display.getBoundingClientRect().height).toBeLessThan(1000);
  });

  it("shows invalid TeX as an error instead of breaking the answer", () => {
    const { container } = render(Markdown, { source: "Före $\\frac{a$ efter" });
    expect(container.querySelector(".katex-error")).not.toBeNull();
    expect(container.textContent).toContain("efter");
  });
});
