/**
 * Vitest setup (vitest.config.ts → setupFiles): what jsdom lacks and Astryx
 * uses, installed once for every jsdom test file. Modal <dialog> (every dialog
 * in the app is one), CSS.escape (Dialog finds its title with it), media
 * queries, layout observers and scrolling. Only fills gaps; a test can still
 * stub any of these itself (vi.stubGlobal, a vi.fn()).
 *
 * jsdom has no top layer and no inertness: a stubbed showModal() only sets
 * `open`, so tests check that a dialog is modal (aria-modal, showModal) rather
 * than that the page behind it is inert.
 */
if (typeof window !== "undefined") {
  const proto = HTMLDialogElement.prototype;
  proto.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  proto.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
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

  window.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false
  })) as unknown as typeof window.matchMedia;

  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;

  window.scrollTo = () => {};
  Element.prototype.scrollIntoView ??= () => {};
}
