// @vitest-environment jsdom
import { act, cleanup, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";

// KaTeX (rehype-katex and its CSS) arrives on demand. Each test starts from
// fresh modules; the real typesetting module is wrapped to count and gate loads.
const state = { loads: 0, fail: false };
// Transform KaTeX once up front, so no test's wait includes compiling it.
beforeAll(() => vi.importActual("./math-katex"), 30_000);
let arrive = () => {};
beforeEach(() => {
  vi.resetModules();
  state.loads = 0;
  state.fail = false;
  const arrived = new Promise<void>((resolve) => (arrive = resolve));
  // The idle preload waits for a browser that is idle, here only when a test says so.
  vi.stubGlobal("requestIdleCallback", () => 0);
  vi.doMock("./math-katex", async (importOriginal) => {
    state.loads += 1;
    await arrived;
    if (state.fail) throw new Error("Failed to fetch dynamically imported module");
    return importOriginal();
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function renderAnswer(text: string) {
  const { MessageResponse } = await import("./message");
  return renderInApp(<MessageResponse isAnimating={false}>{text}</MessageResponse>);
}

it("loads KaTeX for an answer without math only once the browser is idle", async () => {
  const idle: (() => void)[] = [];
  vi.stubGlobal("requestIdleCallback", (run: () => void) => idle.push(run));
  const { container } = await renderAnswer("Nämnden godkänner förslaget, 120 kr per timme.");
  await act(async () => arrive());
  expect(container.textContent).toContain("120 kr per timme");
  expect(state.loads).toBe(0);

  await act(async () => idle.forEach((run) => run()));
  expect(state.loads).toBe(1);
  expect(container.textContent).toContain("120 kr per timme");
});

it("typesets a formula on first paint once KaTeX has loaded while idle", async () => {
  vi.stubGlobal("requestIdleCallback", (run: () => void) => run());
  await act(async () => arrive());
  await renderAnswer("Inget här.");
  const { katexStore } = await import("./math");
  await waitFor(() => expect(katexStore.typeset()).not.toBeNull());

  const { MessageResponse } = await import("./message");
  const { container } = renderInApp(
    <MessageResponse isAnimating={false}>{"Låt $x^2$ vara talet."}</MessageResponse>
  );
  expect(container.querySelector(".katex")).not.toBeNull();
});

it("shows a formula as written until KaTeX arrives, then typesets it", async () => {
  const { container } = await renderAnswer("Låt $x^2$ vara talet.");
  await waitFor(() => expect(state.loads).toBe(1));
  expect(container.querySelector(".katex")).toBeNull();
  expect(container.textContent).toContain("x^2");

  await act(async () => arrive());
  await waitFor(() => expect(container.querySelector(".katex")).not.toBeNull());
});

it.each([
  ["a backtick math fence", "```math\nx^2\n```"],
  ["a tilde math fence", "~~~math\nx^2\n~~~"],
  ["a fence with a space before math", "``` math\nx^2\n```"],
  ["a fence with a tab before math", "```\tmath\nx^2\n```"],
  ["\\( and \\)", "Låt \\(x^2\\) vara talet."],
  ["\\[ and \\]", "\\[x^2\\]"],
  ["$$ on its own lines", "$$\nx^2\n$$"],
  ["a fence that spells math with a character reference", "```m&#97;th\nx^2\n```"],
  ["raw HTML classed as math", '<code class="language-math">x^2</code>']
])("typesets %s when it is the first answer with math", async (_name, text) => {
  const { container } = await renderAnswer(text);
  await waitFor(() => expect(state.loads).toBe(1));
  await act(async () => arrive());
  await waitFor(() => expect(container.querySelector(".katex")).not.toBeNull());
});

it("shows a display formula's TeX without code controls or a focus stop until KaTeX arrives", async () => {
  const { container } = await renderAnswer("Pythagoras:\n\n$$\nx^2 + y^2 = z^2\n$$");
  await waitFor(() => expect(state.loads).toBe(1));
  expect(container.textContent).toContain("x^2 + y^2 = z^2");
  expect(container.querySelector("pre, [tabindex], [role='region']")).toBeNull();
  expect(screen.queryByRole("button")).toBeNull();

  await act(async () => arrive());
  await waitFor(() => expect(container.querySelector(".katex-display")).not.toBeNull());
  expect(screen.queryByRole("button")).toBeNull();
});

it.each([
  [
    "a display formula with a link inside",
    '<pre><code class="language-math"><a href="https://example.test">x</a>^2</code></pre>',
    "x^2"
  ],
  [
    "a display formula with text beside its code",
    '<pre>före<code class="language-math">x^2</code>efter</pre>',
    "förex^2efter"
  ],
  [
    "an inline formula with a link inside",
    'Låt <code class="language-math"><a href="https://example.test">x</a>^2</code> vara talet.',
    "x^2"
  ]
])("shows %s as its TeX alone until KaTeX arrives", async (_name, text, source) => {
  const { container } = await renderAnswer(text);
  await waitFor(() => expect(state.loads).toBe(1));
  expect(container.textContent).toContain(source);
  expect(container.querySelector("a, button, pre, [tabindex], [role='region']")).toBeNull();

  await act(async () => arrive());
  await waitFor(() => expect(container.querySelector(".katex")).not.toBeNull());
});

it("keeps the formula as written when KaTeX cannot be fetched, and the next answer tries again", async () => {
  state.fail = true;
  const { MessageResponse } = await import("./message");
  const { container, rerender } = await renderAnswer("Låt $x^2$ vara");
  await act(async () => arrive());
  await waitFor(() => expect(state.loads).toBe(1));
  expect(container.textContent).toContain("x^2");
  expect(container.querySelector(".katex")).toBeNull();

  // The same answer streaming on does not try again with every token.
  rerender(<MessageResponse isAnimating>{"Låt $x^2$ vara talet"}</MessageResponse>);
  rerender(<MessageResponse isAnimating>{"Låt $x^2$ vara talet och $y$."}</MessageResponse>);
  await act(async () => {});
  expect(state.loads).toBe(1);

  // The next answer that can contain math loads KaTeX anew.
  state.fail = false;
  rerender(
    <>
      <MessageResponse isAnimating={false}>{"Låt $x^2$ vara talet och $y$."}</MessageResponse>
      <MessageResponse isAnimating={false}>{"Och $y^2$ också."}</MessageResponse>
    </>
  );
  await waitFor(() => expect(state.loads).toBe(2));
  await waitFor(() => expect(container.querySelectorAll(".katex")).toHaveLength(3));
});

it("makes a rich-text copy made before KaTeX arrives wait for it, then carry MathML", async () => {
  const { renderAnswerForClipboard } = await import("./answer-clipboard");
  const copy = renderAnswerForClipboard("Låt $x^2$ vara talet.");
  expect(copy.plainText).toBe("Låt x^2 vara talet.");
  let html: string | undefined;
  const copied = copy.html().then((value) => (html = value));
  await waitFor(() => expect(state.loads).toBe(1));
  expect(html).toBeUndefined();

  arrive();
  await copied;
  expect(html).toContain("<math");
});

it("fails a rich-text copy of a formula when KaTeX cannot be fetched; the next copy loads it anew", async () => {
  state.fail = true;
  const { renderAnswerForClipboard } = await import("./answer-clipboard");
  arrive();
  await expect(renderAnswerForClipboard("Låt $x^2$ vara talet.").html()).rejects.toThrow();

  state.fail = false;
  await expect(renderAnswerForClipboard("Låt $x^2$ vara talet.").html()).resolves.toContain(
    "<math"
  );
  expect(state.loads).toBe(2);
});
