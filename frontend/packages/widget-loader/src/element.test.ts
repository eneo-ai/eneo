import { page } from "@vitest/browser/context";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { EneoWidgetElement } from "./element";
import { BRIDGE_NAMESPACE } from "./protocol";

const WIDGET_ID = "wgt_test123";

beforeAll(() => {
  // The test page is English; the loader falls back to the document language.
  document.documentElement.lang = "sv";
  EneoWidgetElement.defaultBaseUrl = location.origin;
  if (!customElements.get("eneo-widget")) customElements.define("eneo-widget", EneoWidgetElement);
});

afterEach(() => {
  document.querySelectorAll("eneo-widget").forEach((el) => el.remove());
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

function mount(attributes: Record<string, string> = {}): EneoWidgetElement {
  const element = document.createElement("eneo-widget") as EneoWidgetElement;
  element.setAttribute("widget-id", WIDGET_ID);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  document.body.appendChild(element);
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

const frameMessage = (type: string, payload?: unknown) => ({
  ns: BRIDGE_NAMESPACE,
  v: 1,
  type,
  payload
});

describe("launcher", () => {
  it("is a labelled disclosure button that controls the panel", () => {
    const element = mount();
    const launcher = launcherOf(element);
    expect(launcher.getAttribute("aria-haspopup")).toBe("dialog");
    expect(launcher.getAttribute("aria-expanded")).toBe("false");
    expect(launcher.getAttribute("aria-controls")).toBe("eneo-panel");
    expect(element.shadowRoot!.getElementById("eneo-panel")).not.toBeNull();
    expect(launcher.getAttribute("aria-label")).toBe("Öppna chatt");
    expect(frameOf(element)).toBeNull();
  });

  it("uses the requested language and custom label", () => {
    expect(launcherOf(mount({ lang: "en-GB" })).getAttribute("aria-label")).toBe("Open chat");
    expect(launcherOf(mount({ label: "Fråga oss" })).getAttribute("aria-label")).toBe("Fråga oss");
  });

  it("can be hidden for hosts that render their own trigger", () => {
    const element = mount({ launcher: "none" });
    expect(launcherOf(element).hidden).toBe(true);
    element.removeAttribute("launcher");
    expect(launcherOf(element).hidden).toBe(false);
  });
});

describe("opening", () => {
  it("creates a sandboxed iframe pointing at the embed page with the host origin", () => {
    const element = mount({ "base-url": location.origin + "/", lang: "en" });
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

    const element = mount();
    element.openPanel();
    const sandbox = frameOf(element)!.getAttribute("sandbox")!;
    expect(await submitsIn(sandbox)).toBe(1);
    expect(await submitsIn(sandbox.replace("allow-forms", ""))).toBe(0);
  });

  it("passes a pinned colour scheme along so the first paint matches", () => {
    const element = mount({ "color-scheme": "dark" });
    element.openPanel();
    expect(frameOf(element)!.src).toMatch(/\?origin=[^&]+&scheme=dark$/);
    expect(element.effectiveScheme).toBe("dark");
  });

  it("hands a preview token to the embed page in the fragment", () => {
    const element = mount({ preview: "tok/en" });
    element.openPanel();
    expect(frameOf(element)!.src).toMatch(
      /\?origin=[^&]+&scheme=(light|dark)&preview=1#preview=tok%2Fen$/
    );
  });

  it("uses the Swedish embed route by default", () => {
    const element = mount();
    element.openPanel();
    expect(frameOf(element)!.src).toContain(`/embed/${WIDGET_ID}?origin=`);
    expect(frameOf(element)!.src).not.toContain("/en/embed/");
  });

  it("does not talk to the iframe before it reports ready, then sends theme and open", () => {
    const element = mount({ "color-scheme": "dark" });
    const post = vi.spyOn(element as never, "post" as never);
    element.openPanel();
    expect(post).not.toHaveBeenCalled();

    deliver(element, frameMessage("ready"));
    const sent = post.mock.calls.map((call) => (call as unknown[])[1]);
    expect(sent).toEqual([
      { ns: BRIDGE_NAMESPACE, v: 1, type: "theme", payload: { scheme: "dark" } },
      { ns: BRIDGE_NAMESPACE, v: 1, type: "open" }
    ]);
  });

  it("tells the embed page which scheme the host page actually shows", () => {
    const element = mount();
    const post = vi.spyOn(element as never, "post" as never);
    element.openPanel();
    deliver(element, frameMessage("ready"));
    const theme = (post.mock.calls[0] as unknown[])[1] as { payload: { scheme: string } };
    expect(["light", "dark"]).toContain(theme.payload.scheme);
    expect(theme.payload.scheme).toBe(element.effectiveScheme);
  });

  it("emits DOM events hosts can listen to", () => {
    const element = mount();
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

  it("opens on connect when asked to", () => {
    const element = mount({ "auto-open": "true" });
    expect(element.open).toBe(true);
    expect(frameOf(element)).not.toBeNull();
  });
});

describe("small screens", () => {
  /** Run `body` at the given viewport and put the test page back afterwards. */
  async function atViewport(width: number, height: number, body: () => void): Promise<void> {
    const before = { width: window.innerWidth, height: window.innerHeight };
    await page.viewport(width, height);
    try {
      body();
    } finally {
      await page.viewport(before.width, before.height);
    }
  }

  function hitAtCenter(element: EneoWidgetElement, target: Element): Element | null {
    const box = target.getBoundingClientRect();
    return element.shadowRoot!.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
  }

  it("keeps the launcher on top of the full-screen panel as the close control until the chat is up", async () => {
    await atViewport(375, 812, () => {
      const element = mount();
      element.openPanel();
      const launcher = launcherOf(element);
      // A paused notice or a page that never loads sends no ready message:
      // the launcher is visible, labelled as the close control and is what
      // a tap on it reaches, not the panel covering the page.
      expect(getComputedStyle(launcher).display).not.toBe("none");
      expect(launcher.getAttribute("aria-label")).toBe("Stäng chatt");
      expect(launcher.contains(hitAtCenter(element, launcher))).toBe(true);
      launcher.click();
      expect(element.open).toBe(false);

      // Once the embed page is ready its own header closes the panel.
      element.openPanel();
      deliver(element, frameMessage("ready"));
      expect(element.hasAttribute("ready")).toBe(true);
      expect(getComputedStyle(launcher).display).toBe("none");
    });
  });

  it("leaves the launcher beside the panel on wide screens whatever the frame reports", async () => {
    await atViewport(1024, 768, () => {
      const element = mount();
      element.openPanel();
      const launcher = launcherOf(element);
      expect(getComputedStyle(launcher).display).not.toBe("none");
      deliver(element, frameMessage("ready"));
      expect(getComputedStyle(launcher).display).not.toBe("none");
    });
  });
});

describe("messages from the iframe", () => {
  it("closes the panel and returns focus to the launcher", () => {
    const element = mount();
    launcherOf(element).focus();
    launcherOf(element).click();
    expect(element.open).toBe(true);

    deliver(element, frameMessage("close"));
    expect(element.open).toBe(false);
    expect(launcherOf(element).getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(element);
    expect(element.shadowRoot!.activeElement).toBe(launcherOf(element));
  });

  it("returns focus to the previously focused element when the launcher is hidden", () => {
    const button = document.createElement("button");
    button.textContent = "Fråga";
    document.body.appendChild(button);
    const element = mount({ launcher: "none" });
    button.focus();
    element.openPanel();
    deliver(element, frameMessage("close"));
    expect(document.activeElement).toBe(button);
  });

  it("ignores messages from other origins or windows", () => {
    const element = mount();
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

  it("shows unread counts on the launcher only while closed", () => {
    const element = mount();
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

  it("paints the launcher with the widget's colour for the scheme in effect", () => {
    const element = mount({ "color-scheme": "light" });
    element.openPanel();
    deliver(element, { ...frameMessage("ready"), payload: { colors } });
    const launcher = launcherOf(element);
    expect(launcher.style.getPropertyValue("--_eneo-accent")).toBe("#1F4E79");
    expect(launcher.style.getPropertyValue("--_eneo-on-accent")).toBe("#FFFFFF");

    element.setAttribute("color-scheme", "dark");
    expect(launcher.style.getPropertyValue("--_eneo-accent")).toBe("#9CC7F0");
    expect(launcher.style.getPropertyValue("--_eneo-on-accent")).toBe("#111111");
  });

  it("keeps the default when the embed page sends no colours", () => {
    const element = mount();
    element.openPanel();
    deliver(element, frameMessage("ready"));
    expect(launcherOf(element).style.getPropertyValue("--_eneo-accent")).toBe("");
  });
});

describe("host controls", () => {
  it("forwards colour scheme changes and page context once the frame is ready", () => {
    const element = mount();
    const post = vi.spyOn(element as never, "post" as never);
    element.setContext({ page_url: "https://host.example/page", page_title: "Sida" });
    expect(post).not.toHaveBeenCalled();

    element.openPanel();
    deliver(element, frameMessage("ready"));
    element.setAttribute("color-scheme", "light");
    const types = post.mock.calls.map((call) => ((call as unknown[])[1] as { type: string }).type);
    expect(types).toEqual(["theme", "context", "open", "theme"]);
    expect((post.mock.calls[1] as unknown[])[1]).toMatchObject({
      type: "context",
      payload: { page_url: "https://host.example/page", page_title: "Sida" }
    });
  });

  it("posts only to the Eneo origin", () => {
    const element = mount({ "base-url": "https://eneo.example.se/" });
    expect(element.eneoOrigin).toBe("https://eneo.example.se");
    const postMessage = vi.fn();
    (element as unknown as { post(target: unknown, data: unknown): void }).post(
      { postMessage },
      { type: "open" }
    );
    expect(postMessage).toHaveBeenCalledWith({ type: "open" }, "https://eneo.example.se");
  });

  it("stops listening when removed from the page", () => {
    const element = mount();
    element.openPanel();
    element.remove();
    deliver(element, frameMessage("close"));
    expect(element.open).toBe(true);
  });
});
