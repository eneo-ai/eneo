// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useKeyboardHeight } from "./use-keyboard-height";

function Page() {
  useKeyboardHeight();
  return null;
}

const viewportOf = (height: number, scale = 1) => {
  const viewport = Object.assign(new EventTarget(), { height, scale });
  vi.stubGlobal("visualViewport", viewport);
  return viewport;
};
const resize = (viewport: EventTarget) => viewport.dispatchEvent(new Event("resize"));
const height = () => document.documentElement.style.getPropertyValue("--keyboard-height");
const PAGE = 1000;

beforeEach(() => {
  vi.spyOn(document.documentElement, "clientHeight", "get").mockReturnValue(PAGE);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("useKeyboardHeight", () => {
  it("leaves Safari's pan alone for a field in a dialog, which lies outside the frame", () => {
    const scrollTo = vi.fn();
    vi.stubGlobal("scrollTo", scrollTo);
    const viewport = viewportOf(PAGE);
    render(
      <dialog open>
        <input aria-label="Lower field" />
      </dialog>
    );
    render(<Page />);
    document.querySelector("input")?.focus();
    viewport.height = 400;
    resize(viewport);
    expect(height()).toBe("400px");
    expect(scrollTo).not.toHaveBeenCalled();
  });

  it("fits the frame to what a keyboard leaves, and takes the page's pan back", () => {
    const scrollTo = vi.fn();
    vi.stubGlobal("scrollTo", scrollTo);
    const viewport = viewportOf(PAGE);
    render(<Page />);
    expect(height()).toBe("");
    viewport.height = 400;
    resize(viewport);
    expect(height()).toBe("400px");
    expect(document.documentElement.hasAttribute("data-keyboard")).toBe(true);
    expect(scrollTo).toHaveBeenCalledWith(0, 0);
  });

  it("gives the height back when the keyboard goes", () => {
    vi.stubGlobal("scrollTo", vi.fn());
    const viewport = viewportOf(400);
    render(<Page />);
    resize(viewport);
    viewport.height = PAGE;
    resize(viewport);
    expect(height()).toBe("");
    expect(document.documentElement.hasAttribute("data-keyboard")).toBe(false);
  });

  it("leaves a pinch zoom alone", () => {
    const viewport = viewportOf(300, 2);
    render(<Page />);
    resize(viewport);
    expect(height()).toBe("");
  });
});
