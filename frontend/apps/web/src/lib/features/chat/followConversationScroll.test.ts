import { afterEach, expect, it, vi } from "vitest";
import { followConversationScroll } from "./followConversationScroll";

function setup() {
  let resize!: () => void;
  const observe = vi.fn();
  const disconnect = vi.fn();
  const frames = new Map<number, FrameRequestCallback>();
  let frameId = 0;
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: () => void) {
        resize = callback;
      }
      observe = observe;
      disconnect = disconnect;
    }
  );
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    frames.set(++frameId, callback);
    return frameId;
  });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
  const viewport = Object.assign(new EventTarget(), {
    scrollHeight: 1200,
    clientHeight: 600,
    scrollTop: 600
  });
  const messages = {} as HTMLElement;
  const composer = {} as HTMLElement;
  const away = vi.fn();
  const follower = followConversationScroll(
    viewport as unknown as HTMLElement,
    [messages, composer],
    away
  );
  const flush = () => {
    const pending = [...frames.values()];
    frames.clear();
    pending.forEach((callback) => callback(0));
  };
  const scroll = (top: number) => {
    viewport.scrollTop = top;
    viewport.dispatchEvent(new Event("scroll"));
  };
  flush();
  return {
    viewport,
    messages,
    composer,
    observe,
    disconnect,
    frames,
    resize,
    flush,
    scroll,
    away,
    follower
  };
}

afterEach(() => vi.unstubAllGlobals());

it("follows a late widget and subsequent iframe growth without another text event", () => {
  const h = setup();
  expect(h.observe.mock.calls.map(([node]) => node)).toEqual([h.viewport, h.messages, h.composer]);
  h.viewport.scrollHeight += 450;
  h.resize();
  h.flush();
  expect(h.viewport.scrollTop).toBe(1050);
  h.viewport.scrollHeight += 300;
  h.resize();
  h.flush();
  expect(h.viewport.scrollTop).toBe(1350);
  expect(h.away).toHaveBeenLastCalledWith(false);
});

it("does not mistake a layout-induced scroll event for the reader scrolling away", () => {
  const h = setup();
  h.viewport.scrollHeight += 500;
  h.scroll(600);
  h.resize();
  h.flush();
  expect(h.viewport.scrollTop).toBe(1100);
});

it("preserves the reading position during widget growth until the reader opts back in", () => {
  const h = setup();
  h.scroll(200);
  h.viewport.scrollHeight += 500;
  h.resize();
  h.flush();
  expect(h.viewport.scrollTop).toBe(200);
  expect(h.away).toHaveBeenLastCalledWith(true);
  h.follower.toBottom();
  h.flush();
  expect(h.viewport.scrollTop).toBe(1100);
  h.viewport.scrollHeight += 200;
  h.resize();
  h.flush();
  expect(h.viewport.scrollTop).toBe(1300);
});

it("lets an upward user scroll cancel a pending follow even during growth", () => {
  const h = setup();
  h.viewport.scrollHeight += 400;
  h.resize();
  h.scroll(100);
  h.flush();
  expect(h.viewport.scrollTop).toBe(100);
});

it("resumes following when the reader manually returns near the bottom", () => {
  const h = setup();
  h.scroll(0);
  h.scroll(580);
  h.viewport.scrollHeight += 400;
  h.resize();
  h.flush();
  expect(h.viewport.scrollTop).toBe(1000);
});

it("keeps the bottom visible when the composer or viewport changes size", () => {
  const h = setup();
  h.viewport.clientHeight = 400;
  h.resize();
  h.flush();
  expect(h.viewport.scrollTop).toBe(800);
  h.viewport.scrollHeight += 100;
  h.resize();
  h.flush();
  expect(h.viewport.scrollTop).toBe(900);
});

it("coalesces layout updates and cleans up pending work on navigation", () => {
  const h = setup();
  h.viewport.scrollHeight += 400;
  h.resize();
  h.resize();
  expect(h.frames.size).toBe(1);
  h.follower.destroy();
  expect(h.disconnect).toHaveBeenCalledOnce();
  expect(h.frames.size).toBe(0);
  h.scroll(0);
  h.resize();
  h.flush();
  expect(h.viewport.scrollTop).toBe(0);
  expect(h.away).toHaveBeenCalledTimes(1);
});
