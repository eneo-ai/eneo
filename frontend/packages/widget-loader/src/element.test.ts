import { page } from "@vitest/browser/context";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { EneoWidgetElement } from "./element";
import { BRIDGE_NAMESPACE } from "./protocol";
import { styles } from "./styles";
import { flushSettings, spyOnSeam, stubSettings } from "./testing";

const WIDGET_ID = "wgt_test123";
const testStylesheet = new CSSStyleSheet();
testStylesheet.replaceSync(styles);

beforeAll(() => {
  // The test page is English; the loader falls back to the document language.
  document.documentElement.lang = "sv";
  EneoWidgetElement.defaultBaseUrl = location.origin;
  if (!customElements.get("eneo-widget")) customElements.define("eneo-widget", EneoWidgetElement);
});

beforeEach(() => {
  stubSettings();
});

afterEach(() => {
  document.querySelectorAll("eneo-widget").forEach((el) => el.remove());
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

function attach(attributes: Record<string, string> = {}): EneoWidgetElement {
  const element = document.createElement("eneo-widget") as EneoWidgetElement;
  element.setAttribute("widget-id", WIDGET_ID);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  document.body.appendChild(element);
  // The package's test server does not serve the web app's versioned CSS
  // route. Keep the layout tests using the same source stylesheet.
  element.shadowRoot!.adoptedStyleSheets = [testStylesheet];
  return element;
}

/** An element whose settings request has been answered. */
async function mount(attributes: Record<string, string> = {}): Promise<EneoWidgetElement> {
  const element = attach(attributes);
  await flushSettings();
  return element;
}

function launcherOf(element: EneoWidgetElement): HTMLButtonElement {
  return element.shadowRoot!.querySelector(".launcher") as HTMLButtonElement;
}

function frameOf(element: EneoWidgetElement): HTMLIFrameElement | null {
  return element.shadowRoot!.querySelector("iframe");
}

/** Simulate a message from the iframe; `source` defaults to the frame's window. */
function deliver(
  element: EneoWidgetElement,
  data: unknown,
  overrides: { origin?: string; source?: Window | null } = {}
): void {
  const frame = frameOf(element);
  window.dispatchEvent(
    new MessageEvent("message", {
      data,
      origin: overrides.origin ?? element.eneoOrigin,
      source: "source" in overrides ? overrides.source : frame?.contentWindow
    })
  );
}

/** Run `body` at the given viewport and put the test page back afterwards. */
async function atViewport(
  width: number,
  height: number,
  body: () => void | Promise<void>
): Promise<void> {
  const before = { width: window.innerWidth, height: window.innerHeight };
  await page.viewport(width, height);
  try {
    await body();
  } finally {
    await page.viewport(before.width, before.height);
  }
}

const frameMessage = (type: string, payload?: unknown) => ({
  ns: BRIDGE_NAMESPACE,
  v: 1,
  type,
  payload
});

describe("launcher", () => {
  it("loads versioned CSS from Eneo without an inline style element", async () => {
    const element = await mount();
    const root = element.shadowRoot!;
    const stylesheet = root.querySelector('link[rel="stylesheet"]') as HTMLLinkElement;
    expect(stylesheet.href).toBe(`${location.origin}/widget/${__LOADER_VERSION__}/eneo.css`);
    expect(stylesheet.integrity).toBe(__LOADER_CSS_INTEGRITY__);
    expect(stylesheet.crossOrigin).toBe("anonymous");
    expect(root.querySelector("style")).toBeNull();
  });

  it("is a labelled disclosure button that controls the panel", async () => {
    const element = await mount();
    const launcher = launcherOf(element);
    expect(launcher.getAttribute("aria-haspopup")).toBe("dialog");
    expect(launcher.getAttribute("aria-expanded")).toBe("false");
    expect(launcher.getAttribute("aria-controls")).toBe("eneo-panel");
    const panel = element.shadowRoot!.getElementById("eneo-panel")!;
    expect(panel.getAttribute("role")).toBe("dialog");
    expect(panel.getAttribute("aria-label")).toBe("Chatt");
    expect(launcher.getAttribute("aria-label")).toBe("Öppna chatt");
    expect(frameOf(element)).toBeNull();
  });

  it("uses the requested language and custom label", async () => {
    expect(launcherOf(await mount({ lang: "en-GB" })).getAttribute("aria-label")).toBe("Open chat");
    expect(launcherOf(await mount({ label: "Fråga oss" })).getAttribute("aria-label")).toBe(
      "Fråga oss"
    );
  });

  it("can be hidden for hosts that render their own trigger", async () => {
    const element = await mount({ launcher: "none" });
    expect(launcherOf(element).hidden).toBe(true);
    element.removeAttribute("launcher");
    expect(launcherOf(element).hidden).toBe(false);
  });
});

describe("saved settings", () => {
  const colors = {
    light: { accent: "#1F4E79", on_accent: "#FFFFFF" },
    dark: { accent: "#9CC7F0", on_accent: "#111111" }
  };

  /** A settings request the test answers (or never answers) itself. */
  function heldSettings() {
    let answer: (settings: unknown) => void = () => {};
    const request = spyOnSeam(EneoWidgetElement.prototype, "fetchSettings").mockImplementation(
      () => new Promise((resolve) => (answer = resolve))
    );
    return { request, answer: (settings: unknown) => answer(settings) };
  }

  it("asks the Eneo origin for the widget's settings", async () => {
    const request = stubSettings();
    await mount({ "base-url": "https://eneo.example.se/" });
    expect(request).toHaveBeenCalledWith(`https://eneo.example.se/widget/settings/${WIDGET_ID}`);
  });

  it("shows the launcher only once the settings are in, already in the saved corner", async () => {
    const held = heldSettings();
    const element = attach();
    expect(launcherOf(element).hidden).toBe(true);

    held.answer({ language: "en", position: "bottom-left", colors });
    await flushSettings();

    const launcher = launcherOf(element);
    expect(launcher.hidden).toBe(false);
    expect(element.getAttribute("position")).toBe("bottom-left");
    expect(launcher.getAttribute("aria-label")).toBe("Open chat");
    expect(launcher.style.getPropertyValue("--_eneo-accent")).not.toBe("");
  });

  it("follows later edits over what the snippet was copied with", async () => {
    stubSettings({ language: "en", position: "bottom-left", colors });
    const element = await mount({ lang: "sv", position: "bottom-right" });
    expect(element.getAttribute("position")).toBe("bottom-left");
    expect(element.lang).toBe("en");
    element.openPanel();
    expect(frameOf(element)!.src).toContain(`/en/embed/${WIDGET_ID}?`);
    expect(frameOf(element)!.title).toBe("Chat");
  });

  it("follows the host page while the widget's language is automatic", async () => {
    stubSettings({ language: "auto", position: "bottom-right", colors });
    expect((await mount()).lang).toBe("sv");
    expect((await mount({ lang: "en" })).lang).toBe("en");
  });

  it("falls back to the attributes when no settings arrive, and a late answer never moves it", async () => {
    vi.useFakeTimers();
    try {
      const held = heldSettings();
      const element = attach({ position: "bottom-left" });
      expect(launcherOf(element).hidden).toBe(true);

      await vi.advanceTimersByTimeAsync(3000);
      expect(launcherOf(element).hidden).toBe(false);
      expect(element.getAttribute("position")).toBe("bottom-left");

      held.answer({ language: "en", position: "bottom-right", colors });
      await vi.advanceTimersByTimeAsync(0);
      expect(element.getAttribute("position")).toBe("bottom-left");
      expect(launcherOf(element).style.getPropertyValue("--_eneo-accent")).not.toBe("");
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows the launcher at once when the settings request fails", async () => {
    spyOnSeam(EneoWidgetElement.prototype, "fetchSettings").mockImplementation(() =>
      Promise.reject(new TypeError("blocked by CSP"))
    );
    const element = await mount({ position: "bottom-left" });
    expect(launcherOf(element).hidden).toBe(false);
    expect(element.getAttribute("position")).toBe("bottom-left");
  });

  it("does not show a launcher or open a panel for an inactive widget", async () => {
    spyOnSeam(EneoWidgetElement.prototype, "fetchSettings").mockRestore();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 404 }));
    const element = attach();
    element.openPanel();
    await flushSettings();
    expect(launcherOf(element).hidden).toBe(true);
    expect(element.open).toBe(false);
    expect(frameOf(element)).toBeNull();

    element.openPanel();
    element.prefetch();
    expect(frameOf(element)).toBeNull();
  });

  it("opens only once the settings are in, so the panel appears in the saved corner", async () => {
    const held = heldSettings();
    const element = attach();
    element.openPanel();
    expect(element.open).toBe(false);
    expect(frameOf(element)).toBeNull();

    held.answer({ language: "en", position: "bottom-left", colors });
    await flushSettings();
    expect(element.open).toBe(true);
    expect(element.getAttribute("position")).toBe("bottom-left");
    expect(frameOf(element)!.src).toContain("/en/embed/");
  });

  it("drops an early open when the host closes again before the settings are in", async () => {
    const held = heldSettings();
    const element = attach();
    element.openPanel();
    element.closePanel();
    held.answer(null);
    await flushSettings();
    expect(element.open).toBe(false);
  });

  it("forgets an early open when the host removes it before the settings are in", async () => {
    const held = heldSettings();
    const element = attach();
    element.openPanel();
    element.prefetch();
    const listen = vi.spyOn(window, "addEventListener");
    element.remove();

    held.answer({ position: "bottom-left", colors });
    await flushSettings();
    expect(element.open).toBe(false);
    expect(frameOf(element)).toBeNull();
    expect(listen.mock.calls.map(([type]) => type)).not.toContain("resize");
  });

  it("never asks for settings in a preview, which shows what the editor passes in", async () => {
    const request = stubSettings({ position: "bottom-right" });
    const element = attach({ preview: "tok", position: "bottom-left" });
    expect(request).not.toHaveBeenCalled();
    expect(launcherOf(element).hidden).toBe(false);
    expect(element.getAttribute("position")).toBe("bottom-left");
  });
});

describe("opening", () => {
  it("creates a sandboxed iframe pointing at the embed page with the host origin", async () => {
    const element = await mount({ "base-url": location.origin + "/", lang: "en" });
    launcherOf(element).click();

    const frame = frameOf(element)!;
    expect(frame).not.toBeNull();
    expect(frame.src).toMatch(
      new RegExp(
        `^${location.origin}/en/embed/${WIDGET_ID}\\?origin=${encodeURIComponent(location.origin)}&scheme=(light|dark)$`
      )
    );
    expect(frame.getAttribute("sandbox")).toContain("allow-scripts");
    expect(frame.getAttribute("sandbox")).toContain("allow-same-origin");
    expect(frame.getAttribute("sandbox")).toContain("allow-forms");
    expect(frame.getAttribute("sandbox")).not.toContain("allow-top-navigation");
    expect(frame.getAttribute("referrerpolicy")).toBe("strict-origin");
    expect(frame.title).toBe("Chat");
    expect(element.hasAttribute("open")).toBe(true);
    expect(launcherOf(element).getAttribute("aria-expanded")).toBe("true");
    expect(element.shadowRoot!.querySelector(".panel")!.hasAttribute("hidden")).toBe(false);
  });

  it("lets the embed page's forms submit inside the sandbox", async () => {
    // The composer's send arrow and the comment dialog's Send are submit
    // buttons; a sandbox without allow-forms drops the submit event itself.
    async function submitsIn(sandbox: string): Promise<number> {
      const frame = document.createElement("iframe");
      frame.setAttribute("sandbox", sandbox);
      frame.srcdoc = '<form><button type="submit">Skicka</button></form>';
      const loaded = new Promise((resolve) => frame.addEventListener("load", resolve));
      document.body.appendChild(frame);
      await loaded;
      let submits = 0;
      frame.contentDocument!.querySelector("form")!.addEventListener("submit", (event) => {
        event.preventDefault();
        submits += 1;
      });
      frame.contentDocument!.querySelector("button")!.click();
      return submits;
    }

    const element = await mount();
    element.openPanel();
    const sandbox = frameOf(element)!.getAttribute("sandbox")!;
    expect(await submitsIn(sandbox)).toBe(1);
    expect(await submitsIn(sandbox.replace("allow-forms", ""))).toBe(0);
  });

  it("passes a pinned colour scheme along so the first paint matches", async () => {
    const element = await mount({ "color-scheme": "dark" });
    element.openPanel();
    expect(frameOf(element)!.src).toMatch(/\?origin=[^&]+&scheme=dark$/);
    expect(element.effectiveScheme).toBe("dark");
  });

  it("hands a preview token to the embed page in the fragment", async () => {
    const element = await mount({ preview: "tok/en" });
    element.openPanel();
    expect(frameOf(element)!.src).toMatch(
      /\?origin=[^&]+&scheme=(light|dark)&preview=1#preview=tok%2Fen$/
    );
  });

  it("uses the Swedish embed route by default", async () => {
    const element = await mount();
    element.openPanel();
    expect(frameOf(element)!.src).toContain(`/embed/${WIDGET_ID}?origin=`);
    expect(frameOf(element)!.src).not.toContain("/en/embed/");
  });

  it("does not talk to the iframe before it reports ready, then sends theme, open and layout", async () => {
    await atViewport(1024, 768, async () => {
      const element = await mount({ "color-scheme": "dark" });
      const post = spyOnSeam(element, "post");
      element.openPanel();
      expect(post).not.toHaveBeenCalled();

      deliver(element, frameMessage("ready"));
      const sent = post.mock.calls.map((call) => (call as unknown[])[1]);
      expect(sent).toEqual([
        { ns: BRIDGE_NAMESPACE, v: 1, type: "theme", payload: { scheme: "dark" } },
        { ns: BRIDGE_NAMESPACE, v: 1, type: "open" },
        { ns: BRIDGE_NAMESPACE, v: 1, type: "layout", payload: { full: false, expanded: false } }
      ]);
    });
  });

  it("tells the embed page which scheme the host page actually shows", async () => {
    const element = await mount();
    const post = spyOnSeam(element, "post");
    element.openPanel();
    deliver(element, frameMessage("ready"));
    const theme = (post.mock.calls[0] as unknown[])[1] as { payload: { scheme: string } };
    expect(["light", "dark"]).toContain(theme.payload.scheme);
    expect(theme.payload.scheme).toBe(element.effectiveScheme);
  });

  it("emits DOM events hosts can listen to", async () => {
    const element = await mount();
    const seen: string[] = [];
    for (const name of ["open", "ready", "close", "conversation_started"]) {
      document.addEventListener(`eneo-widget:${name}`, () => seen.push(name));
    }
    element.openPanel();
    deliver(element, frameMessage("ready"));
    deliver(element, frameMessage("conversation_started", { session_id: "s1" }));
    deliver(element, frameMessage("close"));
    expect(seen).toEqual(["open", "ready", "conversation_started", "close"]);
  });

  it("opens on connect when asked to", async () => {
    const element = await mount({ "auto-open": "true" });
    expect(element.open).toBe(true);
    expect(frameOf(element)).not.toBeNull();
  });

  it("names the frame after the widget once the embed page reports its title", async () => {
    const element = await mount();
    element.openPanel();
    expect(frameOf(element)!.title).toBe("Chatt");
    deliver(element, frameMessage("ready", { title: "Fråga kommunen" }));
    expect(frameOf(element)!.title).toBe("Fråga kommunen");

    const named = await mount({ "frame-title": "Chatta med oss" });
    named.openPanel();
    deliver(named, frameMessage("ready", { title: "Fråga kommunen" }));
    expect(frameOf(named)!.title).toBe("Chatta med oss");
  });
});

describe("Escape on the host page", () => {
  // Composed like a real key press, so it leaves the launcher's shadow root.
  const escape = (target: EventTarget) =>
    target.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Escape",
        bubbles: true,
        cancelable: true,
        composed: true
      })
    );

  it("closes the panel and leaves focus where the visitor moved to", async () => {
    // A floating panel: the page beside it stays reachable.
    await atViewport(1024, 768, async () => {
      const link = document.createElement("a");
      link.href = "#kontakt";
      link.textContent = "Kontakt";
      document.body.appendChild(link);
      const element = await mount();
      element.openPanel();
      link.focus();

      escape(link);
      expect(element.open).toBe(false);
      expect(launcherOf(element).getAttribute("aria-expanded")).toBe("false");
      expect(document.activeElement).toBe(link);
    });
  });

  it("closes from the launcher and keeps focus on it", async () => {
    const element = await mount();
    launcherOf(element).focus();
    launcherOf(element).click();
    escape(launcherOf(element));
    expect(element.open).toBe(false);
    expect(element.shadowRoot!.activeElement).toBe(launcherOf(element));
  });

  it("leaves an Escape the page handled itself alone", async () => {
    await atViewport(1024, 768, async () => {
      const menu = document.createElement("button");
      menu.addEventListener("keydown", (event) => event.preventDefault());
      document.body.appendChild(menu);
      const element = await mount();
      element.openPanel();
      menu.focus();
      escape(menu);
      expect(element.open).toBe(true);
    });
  });

  it("only listens while the panel is open", async () => {
    const element = await mount();
    const close = vi.spyOn(element, "closePanel");
    escape(document.body);
    expect(close).not.toHaveBeenCalled();
    element.openPanel();
    element.closePanel();
    close.mockClear();
    escape(document.body);
    expect(close).not.toHaveBeenCalled();
  });
});

describe("small screens", () => {
  /** Host content around the widget, plus an element the page itself made inert. */
  function hostPage(): { main: HTMLElement; aside: HTMLElement } {
    const main = document.createElement("main");
    main.innerHTML = "<button>Sök</button>";
    const aside = document.createElement("aside");
    aside.setAttribute("inert", "");
    document.body.append(main, aside);
    return { main, aside };
  }

  function panelOf(element: EneoWidgetElement): HTMLElement {
    return element.shadowRoot!.getElementById("eneo-panel")!;
  }

  it("is a modal dialog with the page behind it inert, until it closes", async () => {
    await atViewport(375, 812, async () => {
      const { main, aside } = hostPage();
      const element = await mount();
      element.openPanel();
      expect(panelOf(element).getAttribute("aria-modal")).toBe("true");
      expect(main.hasAttribute("inert")).toBe(true);

      element.closePanel();
      expect(panelOf(element).hasAttribute("aria-modal")).toBe(false);
      expect(main.hasAttribute("inert")).toBe(false);
      // What the page made inert itself stays that way.
      expect(aside.hasAttribute("inert")).toBe(true);
    });
  });

  it("fills a short viewport too, such as a laptop zoomed to 200 %", async () => {
    await atViewport(1280, 360, async () => {
      const { main } = hostPage();
      const element = await mount();
      element.openPanel();
      expect(element.fullScreen).toBe(true);
      expect(panelOf(element).getAttribute("aria-modal")).toBe("true");
      expect(main.hasAttribute("inert")).toBe(true);
      expect(getComputedStyle(panelOf(element)).position).toBe("fixed");
    });
  });

  it("becomes modal when the viewport shrinks while open", async () => {
    const { main } = hostPage();
    const element = await mount();
    await atViewport(1024, 768, async () => {
      element.openPanel();
      expect(panelOf(element).hasAttribute("aria-modal")).toBe(false);
      expect(main.hasAttribute("inert")).toBe(false);
      await page.viewport(375, 812);
      await vi.waitFor(() => expect(main.hasAttribute("inert")).toBe(true));
      expect(panelOf(element).getAttribute("aria-modal")).toBe("true");
    });
  });

  it("never leaves the page inert when the widget is removed while open", async () => {
    await atViewport(375, 812, async () => {
      const { main } = hostPage();
      const element = await mount();
      element.openPanel();
      expect(main.hasAttribute("inert")).toBe(true);
      element.remove();
      expect(main.hasAttribute("inert")).toBe(false);
    });
  });

  function hitAtCenter(element: EneoWidgetElement, target: Element): Element | null {
    const box = target.getBoundingClientRect();
    return element.shadowRoot!.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
  }

  it("shows a loading status until the iframe document loads, even without a ready handshake", async () => {
    const element = await mount();
    element.openPanel();
    const loading = element.shadowRoot!.querySelector<HTMLElement>(".loading-state")!;
    expect(loading.querySelector("[role='status']")!.textContent).toBe("Laddar chatten…");
    expect(getComputedStyle(loading).display).not.toBe("none");
    expect(getComputedStyle(frameOf(element)!).visibility).toBe("hidden");
    // An unavailable/error document must remain visible without chat JS.
    frameOf(element)!.dispatchEvent(new Event("load"));
    expect(element.hasAttribute("ready")).toBe(false);
    expect(getComputedStyle(loading).display).toBe("none");
    expect(getComputedStyle(frameOf(element)!).visibility).toBe("visible");
  });

  it("keeps a close control above the chat while loading, without a floating button over the composer", async () => {
    await atViewport(375, 812, async () => {
      const element = await mount();
      element.openPanel();
      const launcher = launcherOf(element);
      const close = element.shadowRoot!.querySelector<HTMLButtonElement>(".loading-close button")!;
      // This must work even if the iframe never sends ready, including when
      // the host uses its own trigger and configures launcher="none".
      expect(getComputedStyle(launcher).display).toBe("none");
      expect(close.getAttribute("aria-label")).toBe("Stäng chatt");
      expect(element.shadowRoot!.activeElement).toBe(close);
      await vi.waitFor(() => expect(close.contains(hitAtCenter(element, close))).toBe(true));
      await vi.waitFor(() =>
        expect(panelOf(element).getBoundingClientRect().bottom).toBeCloseTo(window.innerHeight, 0)
      );
      const panel = panelOf(element).getBoundingClientRect();
      const frame = frameOf(element)!.getBoundingClientRect();
      expect(panel.top).toBeGreaterThan(0);
      expect(panel.bottom).toBeCloseTo(window.innerHeight, 0);
      expect(close.getBoundingClientRect().bottom).toBeLessThanOrEqual(frame.top);
      close.click();
      expect(element.open).toBe(false);

      // Once the embed page is ready its own header closes the panel.
      element.openPanel();
      deliver(element, frameMessage("ready"));
      expect(element.hasAttribute("ready")).toBe(true);
      expect(getComputedStyle(element.shadowRoot!.querySelector(".loading-state")!).display).toBe(
        "none"
      );
      expect(getComputedStyle(launcher).display).toBe("none");
      expect(getComputedStyle(close.parentElement!).display).toBe("none");
    });
  });

  it("can close an unresponsive mobile frame when the host hides the launcher", async () => {
    await atViewport(375, 812, async () => {
      const element = await mount({ launcher: "none" });
      element.openPanel();
      element.shadowRoot!.querySelector<HTMLButtonElement>(".loading-close button")!.click();
      expect(element.open).toBe(false);
    });
  });

  it("keeps the phone sheet's rounded top when the visible window gets shorter", async () => {
    await atViewport(375, 812, async () => {
      const element = await mount();
      element.openPanel();
      await page.viewport(375, 360);
      const panel = panelOf(element);
      await vi.waitFor(() => expect(panel.getBoundingClientRect().bottom).toBeCloseTo(360, 0));
      expect(panel.getBoundingClientRect().top).toBeGreaterThan(0);
      expect(getComputedStyle(panel).borderTopLeftRadius).toBe("20px");
      expect(getComputedStyle(panel).borderTopRightRadius).toBe("20px");
      expect(getComputedStyle(launcherOf(element)).display).toBe("none");
    });
  });

  it("restores the host's scroll position and inline styles after closing or removal", async () => {
    await atViewport(375, 812, async () => {
      const before = document.body.getAttribute("style");
      const overflow = document.documentElement.style.overflow;
      const content = document.createElement("div");
      content.style.height = "3000px";
      document.body.append(content);
      document.body.style.position = "relative";
      document.body.style.top = "3px";
      document.documentElement.style.overflow = "scroll";
      const element = await mount();
      try {
        for (const remove of [false, true]) {
          window.scrollTo({ top: 400, behavior: "instant" });
          element.openPanel();
          expect(getComputedStyle(document.body).position).toBe("fixed");
          expect(document.documentElement.style.overflow).toBe("hidden");
          if (remove) element.remove();
          else element.closePanel();
          expect(document.body.style.position).toBe("relative");
          expect(document.body.style.top).toBe("3px");
          expect(document.documentElement.style.overflow).toBe("scroll");
          expect(window.scrollY).toBe(400);
        }
      } finally {
        element.remove();
        if (before === null) document.body.removeAttribute("style");
        else document.body.setAttribute("style", before);
        document.documentElement.style.overflow = overflow;
        window.scrollTo({ top: 0, behavior: "instant" });
      }
    });
  });

  it("leaves the launcher beside a non-modal panel on wide screens whatever the frame reports", async () => {
    await atViewport(1024, 768, async () => {
      const { main } = hostPage();
      const element = await mount();
      element.openPanel();
      const launcher = launcherOf(element);
      expect(getComputedStyle(launcher).display).not.toBe("none");
      deliver(element, frameMessage("ready"));
      expect(getComputedStyle(launcher).display).not.toBe("none");
      // The page stays usable beside the chat.
      expect(panelOf(element).hasAttribute("aria-modal")).toBe(false);
      expect(main.hasAttribute("inert")).toBe(false);
    });
  });
});

describe("expanding from the chat", () => {
  function panelOf(element: EneoWidgetElement): HTMLElement {
    return element.shadowRoot!.getElementById("eneo-panel")!;
  }

  /** The layout messages the loader sent the embed page, in order. */
  function layouts(post: ReturnType<typeof spyOnSeam>): unknown[] {
    return post.mock.calls
      .map((call) => (call as unknown[])[1] as { type: string; payload?: unknown })
      .filter((message) => message.type === "layout")
      .map((message) => message.payload);
  }

  it("grows the panel over the page at the chat's request and shrinks it back", async () => {
    await atViewport(1024, 768, async () => {
      const main = document.createElement("main");
      main.innerHTML = "<button>Sök</button>";
      document.body.append(main);
      const element = await mount();
      const post = spyOnSeam(element, "post");
      element.openPanel();
      deliver(element, frameMessage("ready"));
      expect(element.expanded).toBe(false);
      expect(getComputedStyle(panelOf(element)).position).toBe("absolute");

      deliver(element, frameMessage("expand"));
      expect(element.expanded).toBe(true);
      expect(element.hasAttribute("expanded")).toBe(true);
      // The same modal, full-viewport panel as on a small screen.
      expect(getComputedStyle(panelOf(element)).position).toBe("fixed");
      expect(panelOf(element).getAttribute("aria-modal")).toBe("true");
      expect(main.hasAttribute("inert")).toBe(true);
      // The chat's header shrinks and closes the panel; no launcher under it.
      expect(getComputedStyle(launcherOf(element)).display).toBe("none");

      deliver(element, frameMessage("collapse"));
      expect(element.expanded).toBe(false);
      expect(element.hasAttribute("expanded")).toBe(false);
      expect(getComputedStyle(panelOf(element)).position).toBe("absolute");
      expect(panelOf(element).hasAttribute("aria-modal")).toBe(false);
      expect(main.hasAttribute("inert")).toBe(false);
      expect(getComputedStyle(launcherOf(element)).display).not.toBe("none");

      expect(layouts(post)).toEqual([
        { full: false, expanded: false },
        { full: true, expanded: true },
        { full: false, expanded: false }
      ]);
    });
  });

  it("ignores a request while the panel is closed", async () => {
    await atViewport(1024, 768, async () => {
      const element = await mount();
      element.prefetch();
      deliver(element, frameMessage("ready"));
      deliver(element, frameMessage("expand"));
      expect(element.expanded).toBe(false);
      expect(element.hasAttribute("expanded")).toBe(false);
    });
  });

  it("opens beside the page again after closing, with the launcher back for focus", async () => {
    await atViewport(1024, 768, async () => {
      const element = await mount();
      launcherOf(element).focus();
      launcherOf(element).click();
      deliver(element, frameMessage("ready"));
      deliver(element, frameMessage("expand"));
      expect(element.expanded).toBe(true);

      deliver(element, frameMessage("close"));
      expect(element.open).toBe(false);
      expect(element.expanded).toBe(false);
      expect(element.hasAttribute("expanded")).toBe(false);
      expect(element.shadowRoot!.activeElement).toBe(launcherOf(element));

      element.openPanel();
      expect(element.expanded).toBe(false);
      expect(getComputedStyle(panelOf(element)).position).toBe("absolute");
    });
  });

  it("reports a small screen as already full, and a layout only when it changes", async () => {
    await atViewport(375, 812, async () => {
      const element = await mount();
      const post = spyOnSeam(element, "post");
      element.openPanel();
      deliver(element, frameMessage("ready"));
      expect(layouts(post)).toEqual([{ full: true, expanded: false }]);

      // Viewport scrolls and resizes re-run the layout without repeating it.
      window.dispatchEvent(new Event("resize"));
      window.visualViewport?.dispatchEvent(new Event("scroll"));
      expect(layouts(post)).toEqual([{ full: true, expanded: false }]);
    });
  });

  it("tells the embed page the layout again after it reloads", async () => {
    await atViewport(1024, 768, async () => {
      const element = await mount();
      const post = spyOnSeam(element, "post");
      element.openPanel();
      deliver(element, frameMessage("ready"));
      deliver(element, frameMessage("ready"));
      expect(layouts(post)).toEqual([
        { full: false, expanded: false },
        { full: false, expanded: false }
      ]);
    });
  });
});

describe("messages from the iframe", () => {
  it("closes the panel and returns focus to the launcher", async () => {
    const element = await mount();
    launcherOf(element).focus();
    launcherOf(element).click();
    expect(element.open).toBe(true);

    deliver(element, frameMessage("close"));
    expect(element.open).toBe(false);
    expect(launcherOf(element).getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(element);
    expect(element.shadowRoot!.activeElement).toBe(launcherOf(element));
  });

  it("returns focus to the previously focused element when the launcher is hidden", async () => {
    const button = document.createElement("button");
    button.textContent = "Fråga";
    document.body.appendChild(button);
    const element = await mount({ launcher: "none" });
    button.focus();
    element.openPanel();
    deliver(element, frameMessage("close"));
    expect(document.activeElement).toBe(button);
  });

  it("ignores messages from other origins or windows", async () => {
    const element = await mount();
    element.openPanel();
    deliver(element, frameMessage("close"), { origin: "https://evil.example" });
    expect(element.open).toBe(true);
    deliver(element, frameMessage("close"), { source: window });
    expect(element.open).toBe(true);
    deliver(element, { ...frameMessage("close"), ns: "other" });
    expect(element.open).toBe(true);
    deliver(element, frameMessage("close"));
    expect(element.open).toBe(false);
  });

  it("shows unread counts on the launcher only while closed", async () => {
    const element = await mount();
    element.openPanel();
    deliver(element, frameMessage("ready"));
    deliver(element, frameMessage("unread", { count: 3 }));
    expect(launcherOf(element).getAttribute("aria-label")).toBe("Stäng chatt");

    deliver(element, frameMessage("close"));
    deliver(element, frameMessage("unread", { count: 3 }));
    expect(launcherOf(element).getAttribute("aria-label")).toBe("Öppna chatt, 3 nya meddelanden");
    const badge = element.shadowRoot!.querySelector(".badge") as HTMLElement;
    expect(badge.hidden).toBe(false);
    expect(badge.textContent).toBe("3");

    element.openPanel();
    expect(badge.hidden).toBe(true);
    expect(launcherOf(element).getAttribute("aria-label")).toBe("Stäng chatt");
  });
});

describe("launcher colours", () => {
  const colors = {
    light: { accent: "#1F4E79", on_accent: "#FFFFFF" },
    dark: { accent: "#9CC7F0", on_accent: "#111111" }
  };

  it("paints the launcher with the widget's colour for the scheme in effect", async () => {
    const element = await mount({ "color-scheme": "light" });
    element.openPanel();
    deliver(element, { ...frameMessage("ready"), payload: { colors } });
    const launcher = launcherOf(element);
    expect(launcher.style.getPropertyValue("--_eneo-accent")).toBe("#1F4E79");
    expect(launcher.style.getPropertyValue("--_eneo-on-accent")).toBe("#FFFFFF");

    element.setAttribute("color-scheme", "dark");
    expect(launcher.style.getPropertyValue("--_eneo-accent")).toBe("#9CC7F0");
    expect(launcher.style.getPropertyValue("--_eneo-on-accent")).toBe("#111111");
  });

  it("keeps the default when the embed page sends no colours", async () => {
    const element = await mount();
    element.openPanel();
    deliver(element, frameMessage("ready"));
    expect(launcherOf(element).style.getPropertyValue("--_eneo-accent")).toBe("");
  });
});

describe("host controls", () => {
  it("forwards colour scheme changes and page context once the frame is ready", async () => {
    const element = await mount();
    const post = spyOnSeam(element, "post");
    element.setContext({ page_url: "https://host.example/page", page_title: "Sida" });
    expect(post).not.toHaveBeenCalled();

    element.openPanel();
    deliver(element, frameMessage("ready"));
    element.setAttribute("color-scheme", "light");
    const types = post.mock.calls.map((call) => ((call as unknown[])[1] as { type: string }).type);
    expect(types).toEqual(["theme", "context", "open", "layout", "theme"]);
    expect((post.mock.calls[1] as unknown[])[1]).toMatchObject({
      type: "context",
      payload: { page_url: "https://host.example/page", page_title: "Sida" }
    });
  });

  it("posts only to the Eneo origin", async () => {
    const element = await mount({ "base-url": "https://eneo.example.se/" });
    expect(element.eneoOrigin).toBe("https://eneo.example.se");
    const postMessage = vi.fn();
    (element as unknown as { post(target: unknown, data: unknown): void }).post(
      { postMessage },
      { type: "open" }
    );
    expect(postMessage).toHaveBeenCalledWith({ type: "open" }, "https://eneo.example.se");
  });

  it("stops listening when removed from the page", async () => {
    const element = await mount();
    element.openPanel();
    element.remove();
    deliver(element, frameMessage("close"));
    expect(element.open).toBe(true);
  });
});
