/**
 * Vitest setup (vitest.config.ts → setupFiles): what jsdom lacks and the app
 * uses, installed once for every jsdom test file and kept faithful to the
 * browser (Chromium, which the e2e tests drive), so a test passes only when
 * users get the same:
 *
 * - `<dialog>` show()/showModal()/close() (every dialog in the app is a modal
 *   one): opening focuses what Chromium focuses, nothing inside a closed
 *   dialog can take focus, and `close` fires in a later task (advance fake
 *   timers for it);
 * - `CSS.escape` (Astryx Dialog finds its title with it);
 * - `matchMedia`, answered for a desktop viewport unless a test picks another
 *   one with `setViewport`;
 * - `ResizeObserver`, which reports nothing by itself (jsdom has no layout)
 *   until a test reports a size with `reportResize`;
 * - scrolling as a no-op.
 *
 * The viewport, the observers and the fake next/navigation route
 * (src/test/navigation.ts) reset after every test. A test can still stub any
 * of these itself (vi.stubGlobal, vi.spyOn). src/test/setup-dom.test.ts
 * checks the fakes against the browser behaviour they copy.
 *
 * jsdom has no top layer and no inertness: the page behind an open modal
 * stays interactive, so tests check that a dialog is modal (aria-modal,
 * showModal) rather than that the page behind it is inert.
 */
import { cleanup } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach } from "vitest";
import { resetNavigation } from "./navigation";

// Viewport and matchMedia

export type Viewport = {
  /** CSS pixels. */
  width: number;
  height: number;
  /** The primary pointer: a mouse or trackpad (`fine`) or a finger (`coarse`). */
  pointer: "fine" | "coarse";
};

/** A laptop with a mouse: the default. */
export const DESKTOP_VIEWPORT: Viewport = { width: 1280, height: 800, pointer: "fine" };
/** A phone held upright, as in the e2e phone scans (tests/a11y.spec.ts). */
export const PHONE_VIEWPORT: Viewport = { width: 390, height: 844, pointer: "coarse" };

let viewport = DESKTOP_VIEWPORT;

/** CSS pixels per rem/em (the browser default font size). */
const ROOT_FONT_SIZE = 16;

function toPixels(length: string): number {
  const match = /^(-?\d*\.?\d+)(px|rem|em)?$/.exec(length);
  if (!match) return Number.NaN;
  const value = Number(match[1]);
  return match[2] === "rem" || match[2] === "em" ? value * ROOT_FONT_SIZE : value;
}

function compare(left: number, operator: string, right: number): boolean {
  switch (operator) {
    case "<":
      return left < right;
    case "<=":
      return left <= right;
    case ">":
      return left > right;
    case ">=":
      return left >= right;
    default:
      return left === right;
  }
}

/** Mirrors `a < b` to `b > a`, so the dimension is always on the left. */
const MIRRORED: Record<string, string> = { "<": ">", "<=": ">=", ">": "<", ">=": "<=", "=": "=" };

function dimension(name: string): number {
  return name === "width" ? viewport.width : viewport.height;
}

/** One media feature without its parentheses: `min-width: 48rem`, `width < 40rem`, `hover`. */
function matchesFeature(feature: string): boolean {
  const range = /^(?:(\S+)\s*(<=|<|>=|>|=)\s*)?(width|height)(?:\s*(<=|<|>=|>|=)\s*(\S+))?$/.exec(
    feature
  );
  if (range) {
    const [, low, lowOperator, name, highOperator, high] = range;
    const size = dimension(name!);
    if (low === undefined && high === undefined) return size > 0;
    const lowOk = low === undefined || compare(size, MIRRORED[lowOperator!]!, toPixels(low));
    const highOk = high === undefined || compare(size, highOperator!, toPixels(high));
    return lowOk && highOk;
  }

  const [name = "", value = ""] = feature.split(":").map((part) => part.trim());
  const canHover = viewport.pointer === "fine";
  switch (name) {
    case "width":
    case "height":
      return dimension(name) === toPixels(value);
    case "min-width":
    case "min-height":
      return dimension(name.slice(4)) >= toPixels(value);
    case "max-width":
    case "max-height":
      return dimension(name.slice(4)) <= toPixels(value);
    case "pointer":
    case "any-pointer":
      return value === "" || value === viewport.pointer;
    case "hover":
    case "any-hover":
      return value === "none" ? !canHover : canHover && (value === "" || value === "hover");
    case "orientation":
      return value === (viewport.height >= viewport.width ? "portrait" : "landscape");
    // User preferences at their browser defaults.
    case "prefers-reduced-motion":
    case "prefers-contrast":
    case "prefers-reduced-transparency":
      return value === "no-preference";
    case "prefers-color-scheme":
      return value === "light";
    case "forced-colors":
      return value === "none";
    default:
      return false;
  }
}

/** One query of a comma-separated list: `screen and (min-width: 768px)`, `not print`. */
function matchesQuery(query: string): boolean {
  const negated = /^not\s/.test(query);
  const conditions = query
    .replace(/^(not|only)\s+/, "")
    .split(/\s+and\s+/)
    .map((condition) => condition.trim());
  const matches = conditions.every((condition) => {
    if (condition === "all" || condition === "screen") return true;
    const feature = /^\((.*)\)$/.exec(condition);
    return feature ? matchesFeature(feature[1]!.trim()) : false;
  });
  return negated ? !matches : matches;
}

/** Whether a media query list matches the current viewport (unsupported syntax never does). */
function matchesMedia(media: string): boolean {
  if (media.trim() === "") return true;
  return media
    .toLowerCase()
    .split(",")
    .some((query) => matchesQuery(query.trim()));
}

/** Lists with change listeners, told when `setViewport` flips them. */
const listening = new Set<TestMediaQueryList>();

class TestMediaQueryList extends EventTarget implements MediaQueryList {
  onchange: ((this: MediaQueryList, event: MediaQueryListEvent) => unknown) | null = null;
  private reported: boolean;

  constructor(readonly media: string) {
    super();
    this.reported = matchesMedia(media);
  }

  get matches() {
    return matchesMedia(this.media);
  }

  override addEventListener(...args: Parameters<EventTarget["addEventListener"]>) {
    if (args[0] === "change") listening.add(this);
    super.addEventListener(...args);
  }

  addListener(listener: ((this: MediaQueryList, event: MediaQueryListEvent) => unknown) | null) {
    this.addEventListener("change", listener as EventListener | null);
  }

  removeListener(listener: ((this: MediaQueryList, event: MediaQueryListEvent) => unknown) | null) {
    this.removeEventListener("change", listener as EventListener | null);
  }

  /** Fires `change` when the viewport changed whether this list matches. */
  update() {
    const matches = this.matches;
    if (matches === this.reported) return;
    this.reported = matches;
    const event = Object.assign(new Event("change"), { matches, media: this.media });
    this.onchange?.call(this, event as MediaQueryListEvent);
    this.dispatchEvent(event);
  }
}

function applyViewportSize() {
  for (const [name, value] of [
    ["innerWidth", viewport.width],
    ["innerHeight", viewport.height]
  ] as const) {
    Object.defineProperty(window, name, { configurable: true, writable: true, value });
  }
}

/**
 * The viewport `matchMedia` answers for, as a browser resized or turned into a
 * phone would: media query lists fire `change` and the window fires `resize`.
 * Set it before rendering, or wrap the call in `act()` when components are
 * already mounted. Resets to the desktop after each test.
 *
 * @example setViewport("phone"); // 390 × 844, touch
 * @example setViewport({ width: 600, height: 800, pointer: "fine" }); // a narrow window
 */
export function setViewport(next: "desktop" | "phone" | Viewport): void {
  viewport = next === "desktop" ? DESKTOP_VIEWPORT : next === "phone" ? PHONE_VIEWPORT : next;
  applyViewportSize();
  for (const list of listening) list.update();
  window.dispatchEvent(new Event("resize"));
}

// ResizeObserver

/** Which ResizeObservers observe which element. */
const observers = new Map<Element, Set<TestResizeObserver>>();

/**
 * ResizeObserver as in a browser whose elements have no size yet: observing
 * reports nothing (a browser reports only non-zero sizes on observe, and jsdom
 * has no layout); `reportResize` delivers a size, so tests can check what
 * reacts to one.
 */
class TestResizeObserver implements ResizeObserver {
  constructor(private readonly callback: ResizeObserverCallback) {}

  observe(target: Element) {
    const set = observers.get(target) ?? new Set();
    set.add(this);
    observers.set(target, set);
  }

  unobserve(target: Element) {
    observers.get(target)?.delete(this);
  }

  disconnect() {
    for (const set of observers.values()) set.delete(this);
  }

  deliver(entry: ResizeObserverEntry) {
    this.callback([entry], this);
  }
}

/** Elements that a ResizeObserver currently observes. */
export function observedElements(): Element[] {
  return [...observers].filter(([, set]) => set.size > 0).map(([element]) => element);
}

/**
 * Reports a new content size for `target` to every ResizeObserver observing
 * it, as the browser does after layout. Wrap it in `act()`.
 *
 * @example act(() => reportResize(dock, { height: 150 }));
 */
export function reportResize(
  target: Element,
  { width = 0, height = 0 }: { width?: number; height?: number }
): void {
  const rect = { x: 0, y: 0, top: 0, left: 0, width, height, right: width, bottom: height };
  const size = [{ inlineSize: width, blockSize: height }];
  const entry = {
    target,
    contentRect: { ...rect, toJSON: () => rect },
    contentBoxSize: size,
    borderBoxSize: size,
    devicePixelContentBoxSize: size
  } as unknown as ResizeObserverEntry;
  for (const observer of observers.get(target) ?? []) observer.deliver(entry);
}

// Dialogs and focus

/** Elements that can take focus, `tabindex="-1"` included. */
const FOCUSABLE = [
  "a[href]",
  "area[href]",
  "button",
  "input:not([type='hidden'])",
  "select",
  "textarea",
  "iframe",
  "summary",
  "[tabindex]"
].join(", ");

function canTakeFocus(element: HTMLElement): boolean {
  if ((element as HTMLButtonElement).disabled) return false;
  if (element.closest("[hidden], [inert], dialog:not([open])")) return false;
  // Only a closed <details>' summary is rendered.
  const details = element.parentElement?.closest("details:not([open])");
  return !details || (element.tagName === "SUMMARY" && element.parentElement === details);
}

/**
 * What show() and showModal() focus, as Chromium does: the first `[autofocus]`
 * element, else the first element that can take focus in tree order (a
 * `tabindex="-1"` panel too), else the dialog itself.
 */
function focusOpenedDialog(dialog: HTMLDialogElement) {
  const focusable = [...dialog.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(canTakeFocus);
  const target = focusable.find((element) => element.hasAttribute("autofocus")) ?? focusable[0];
  if (target) {
    target.focus();
  } else if (dialog.hasAttribute("tabindex")) {
    dialog.focus();
  } else {
    // jsdom only focuses elements it deems focusable: lend the dialog a tabindex.
    dialog.setAttribute("tabindex", "-1");
    dialog.focus();
    dialog.removeAttribute("tabindex");
  }
}

if (typeof window !== "undefined") {
  const dialog = HTMLDialogElement.prototype;
  const open = function (this: HTMLDialogElement) {
    if (this.open) return;
    this.setAttribute("open", "");
    focusOpenedDialog(this);
  };
  dialog.showModal ??= open;
  dialog.show ??= open;
  // Closing a closed dialog does nothing; `close` fires in a later task.
  dialog.close ??= function (this: HTMLDialogElement, returnValue?: string) {
    if (!this.open) return;
    if (returnValue !== undefined) this.returnValue = returnValue;
    this.removeAttribute("open");
    setTimeout(() => this.dispatchEvent(new Event("close")));
  };

  // As in browsers, a closed <dialog> is not rendered, so nothing inside it
  // can take focus (jsdom has no layout, so it would): sheets and dialogs
  // must place focus after they open.
  const focus = HTMLElement.prototype.focus;
  HTMLElement.prototype.focus = function (this: HTMLElement, options?: FocusOptions) {
    if (this.closest("dialog:not([open])")) return;
    focus.call(this, options);
  };

  if (typeof globalThis.CSS?.escape !== "function") {
    Object.defineProperty(globalThis, "CSS", {
      configurable: true,
      writable: true,
      value: {
        ...globalThis.CSS,
        escape: (value: string) => value.replace(/[^a-zA-Z0-9_-]/g, (char) => `\\${char}`)
      }
    });
  }

  window.matchMedia = (media: string) => new TestMediaQueryList(media);
  globalThis.ResizeObserver = TestResizeObserver;
  applyViewportSize();

  window.scrollTo = () => {};
  Element.prototype.scrollIntoView ??= () => {};

  afterEach(() => {
    // Unmount what the test rendered, and drop its toasts: sonner's store is
    // module-wide, so a toast left behind (errors never time out) reaches the
    // next test's Toaster after this test has ended.
    cleanup();
    toast.dismiss();
    viewport = DESKTOP_VIEWPORT;
    applyViewportSize();
    listening.clear();
    observers.clear();
    resetNavigation();
  });
}
