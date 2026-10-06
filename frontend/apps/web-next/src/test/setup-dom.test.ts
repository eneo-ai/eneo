// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { observedElements, reportResize, setViewport } from "./setup-dom";

// Guards the fakes: each copies what Chromium does, so a component test only
// passes when the browser would behave the same.

const matches = (query: string) => window.matchMedia(query).matches;

describe("matchMedia", () => {
  it("answers for a desktop with a mouse by default", () => {
    expect(window.innerWidth).toBe(1280);
    expect(matches("(min-width: 1024px)")).toBe(true);
    expect(matches("screen and (min-width: 768px)")).toBe(true);
    expect(matches("(width < 48rem)")).toBe(false);
    expect(matches("(max-width: 768px) and (pointer: coarse)")).toBe(false);
    expect(matches("(hover: hover)")).toBe(true);
    expect(matches("(hover: none)")).toBe(false);
    expect(matches("(prefers-reduced-motion: reduce)")).toBe(false);
    expect(matches("(prefers-color-scheme: dark)")).toBe(false);
    expect(matches("print")).toBe(false);
  });

  it("answers for a phone once a test picks one", () => {
    setViewport("phone");
    expect(window.innerWidth).toBe(390);
    expect(matches("(width < 48rem)")).toBe(true);
    expect(matches("(width < 40rem)")).toBe(true);
    expect(matches("(min-width: 768px)")).toBe(false);
    expect(matches("(max-width: 768px) and (pointer: coarse)")).toBe(true);
    expect(matches("(hover: none)")).toBe(true);
    expect(matches("(orientation: portrait)")).toBe(true);
    expect(matches("(400px <= width <= 700px)")).toBe(false);
    expect(matches("(min-width: 1024px), (pointer: coarse)")).toBe(true);
  });

  it("is back on the desktop in the next test", () => {
    expect(matches("(pointer: coarse)")).toBe(false);
    expect(window.innerWidth).toBe(1280);
  });

  it("tells listeners when a query starts or stops matching, and the window that it resized", () => {
    const narrow = window.matchMedia("(width < 48rem)");
    const onChange = vi.fn();
    const onResize = vi.fn();
    narrow.addEventListener("change", onChange);
    window.addEventListener("resize", onResize);

    setViewport({ width: 600, height: 800, pointer: "fine" });
    setViewport({ width: 700, height: 800, pointer: "fine" });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0]![0]).toMatchObject({ matches: true, media: "(width < 48rem)" });
    expect(onResize).toHaveBeenCalledTimes(2);
    window.removeEventListener("resize", onResize);
  });
});

describe("ResizeObserver", () => {
  it("reports nothing on observe, then the sizes a test reports", () => {
    const element = document.createElement("div");
    const callback = vi.fn();
    const observer = new ResizeObserver(callback);
    observer.observe(element);
    expect(callback).not.toHaveBeenCalled();
    expect(observedElements()).toEqual([element]);

    reportResize(element, { width: 320, height: 150 });
    const [entry] = callback.mock.calls[0]![0] as ResizeObserverEntry[];
    expect(entry!.target).toBe(element);
    expect(entry!.contentRect.height).toBe(150);
    expect(entry!.contentBoxSize[0]).toEqual({ inlineSize: 320, blockSize: 150 });

    observer.disconnect();
    expect(observedElements()).toEqual([]);
    reportResize(element, { height: 10 });
    expect(callback).toHaveBeenCalledTimes(1);
  });
});

describe("<dialog>", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  function dialogWith(html: string) {
    const dialog = document.createElement("dialog");
    dialog.innerHTML = html;
    document.body.append(dialog);
    return dialog;
  }

  it("lets nothing inside a closed dialog take focus", () => {
    const dialog = dialogWith("<button>Stäng</button>");
    dialog.querySelector("button")!.focus();
    expect(document.activeElement).toBe(document.body);
  });

  it.each([
    [
      "the first element that can take focus",
      '<div id="hit" tabindex="-1"><button>A</button></div>'
    ],
    ["an [autofocus] element first", '<button>A</button><p id="hit" tabindex="-1" autofocus>B</p>'],
    [
      "no disabled or hidden element",
      '<button disabled>A</button><div hidden><a href="#a">B</a></div><a id="hit" href="#c">C</a>'
    ]
  ])("focuses %s when it opens", (_case, html) => {
    const dialog = dialogWith(html);
    dialog.showModal();
    expect(document.activeElement?.id).toBe("hit");
  });

  it("focuses itself when nothing in it can take focus", () => {
    const dialog = dialogWith("<p>Text</p>");
    dialog.showModal();
    expect(document.activeElement).toBe(dialog);
  });

  it("fires close in a later task, and only when it was open", async () => {
    const dialog = dialogWith("<p>Text</p>");
    const onClose = vi.fn();
    dialog.addEventListener("close", onClose);
    dialog.close();
    dialog.showModal();
    dialog.close();
    expect(dialog.open).toBe(false);
    expect(onClose).not.toHaveBeenCalled();

    await new Promise((resolve) => setTimeout(resolve));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
