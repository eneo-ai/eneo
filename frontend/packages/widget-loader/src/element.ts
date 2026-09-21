import {
  envelope,
  parseFrameMessage,
  type ColorScheme,
  type HostMessage,
  type LauncherColors,
  type PageContext
} from "./protocol";
import { styles } from "./styles";

export type WidgetEventName = "ready" | "open" | "close" | "conversation_started" | "unread";

/** Prefix for the DOM events the element dispatches (bubbling, composed). */
export const EVENT_PREFIX = "eneo-widget:";
/** Dispatched on the document when an element connects; the API replays queued commands on it. */
export const CONNECTED_EVENT = "eneo-widget:connected";

const MOBILE_BREAKPOINT = 640;
const CLOSE_ANIMATION_MS = 180;
// No `allow-forms`: the embed page submits nothing, its composer is a button
// and fetch, and its CSP already pins form-action to itself.
const SANDBOX = "allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox";

type Labels = { open: string; close: string; title: string; unread: (count: number) => string };

const LABELS: Record<string, Labels> = {
  sv: {
    open: "Öppna chatt",
    close: "Stäng chatt",
    title: "Chatt",
    unread: (count) =>
      `Öppna chatt, ${count} ${count === 1 ? "nytt meddelande" : "nya meddelanden"}`
  },
  en: {
    open: "Open chat",
    close: "Close chat",
    title: "Chat",
    unread: (count) => `Open chat, ${count} new ${count === 1 ? "message" : "messages"}`
  }
};

const CHAT_ICON =
  '<svg class="chat" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M4 3h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-5 4v-4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/></svg>';
const CLOSE_ICON =
  '<svg class="close" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/></svg>';

/** The value when it parses as an absolute http(s) URL, else null. */
function httpUrl(value: string): string | null {
  try {
    const url = new URL(value, location.href);
    return url.protocol === "http:" || url.protocol === "https:" ? value : null;
  } catch {
    return null;
  }
}

function reducedMotion(): boolean {
  return typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * `<eneo-widget widget-id="wgt_…">`: a launcher button and, once opened, an
 * iframe with the Eneo embed page. All chat UI lives in the iframe; this
 * element only owns placement, focus and the postMessage bridge.
 */
export class EneoWidgetElement extends HTMLElement {
  /** Origin the loader script was served from; set by the bootstrap. */
  static defaultBaseUrl = "";

  static get observedAttributes(): string[] {
    return ["color-scheme", "label", "launcher"];
  }

  private launcher!: HTMLButtonElement;
  private panel!: HTMLDivElement;
  private badge!: HTMLSpanElement;
  private frame: HTMLIFrameElement | null = null;
  private frameReady = false;
  private pendingOpen = false;
  private isOpen = false;
  private unread = 0;
  private context: PageContext | null = null;
  private colors: LauncherColors | null = null;
  private lastFocus: Element | null = null;
  private closeTimer: ReturnType<typeof setTimeout> | null = null;

  private readonly onMessage = (event: MessageEvent) => this.receive(event);
  private readonly onViewport = () => this.fitViewport();
  private readonly onSchemeChange = () => {
    this.paintLauncher();
    this.sendTheme();
  };
  private schemeQuery: MediaQueryList | null = null;

  get widgetId(): string {
    return this.getAttribute("widget-id") || "";
  }

  get baseUrl(): string {
    // Only an http(s) base may become the frame's address: a CMS that lets
    // editors set data attributes must not get a `javascript:` frame out of it.
    const attribute = this.getAttribute("base-url");
    const raw =
      (attribute && httpUrl(attribute)) || EneoWidgetElement.defaultBaseUrl || location.origin;
    return raw.replace(/\/+$/, "");
  }

  /** Only messages from this origin are accepted and only it receives ours. */
  get eneoOrigin(): string {
    return httpUrl(this.baseUrl) ? new URL(this.baseUrl, location.href).origin : location.origin;
  }

  get lang(): string {
    const raw = this.getAttribute("lang") || document.documentElement.lang || "sv";
    return raw.slice(0, 2).toLowerCase() === "en" ? "en" : "sv";
  }

  get colorScheme(): ColorScheme {
    const raw = this.getAttribute("color-scheme");
    return raw === "light" || raw === "dark" ? raw : "auto";
  }

  /** What the host page actually shows: the attribute, else the visitor's system setting. */
  get effectiveScheme(): "light" | "dark" {
    const pinned = this.colorScheme;
    if (pinned !== "auto") return pinned;
    return typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }

  get open(): boolean {
    return this.isOpen;
  }

  get frameUrl(): string {
    const prefix = this.lang === "en" ? "/en" : "";
    const origin = encodeURIComponent(location.origin);
    const scheme = `&scheme=${this.effectiveScheme}`;
    // Editors test draft widgets with a preview token; the fragment never
    // reaches a server log and the embed page reads it client-side.
    const preview = this.getAttribute("preview");
    const suffix = preview ? `&preview=1#preview=${encodeURIComponent(preview)}` : "";
    return `${this.baseUrl}${prefix}/embed/${encodeURIComponent(this.widgetId)}?origin=${origin}${scheme}${suffix}`;
  }

  private get labels(): Labels {
    return LABELS[this.lang];
  }

  connectedCallback(): void {
    if (!this.shadowRoot) this.render();
    window.addEventListener("message", this.onMessage);
    if (typeof matchMedia === "function") {
      this.schemeQuery = matchMedia("(prefers-color-scheme: dark)");
      this.schemeQuery.addEventListener("change", this.onSchemeChange);
    }
    document.dispatchEvent(new CustomEvent(CONNECTED_EVENT, { detail: this }));
    if (this.getAttribute("auto-open") === "true") this.openPanel();
  }

  disconnectedCallback(): void {
    window.removeEventListener("message", this.onMessage);
    this.schemeQuery?.removeEventListener("change", this.onSchemeChange);
    this.unwatchViewport();
  }

  private sendTheme(): void {
    this.send({ type: "theme", payload: { scheme: this.effectiveScheme } });
  }

  attributeChangedCallback(name: string): void {
    if (!this.shadowRoot) return;
    if (name === "color-scheme") {
      this.paintLauncher();
      this.sendTheme();
    } else {
      this.syncLauncher();
    }
  }

  private render(): void {
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML =
      `<style>${styles}</style>` +
      `<button type="button" part="launcher" class="launcher" aria-haspopup="dialog" aria-expanded="false" aria-controls="eneo-panel">${CHAT_ICON}${CLOSE_ICON}<span class="badge" aria-hidden="true" hidden></span></button>` +
      `<div id="eneo-panel" part="panel" class="panel" hidden></div>`;
    this.launcher = root.querySelector(".launcher") as HTMLButtonElement;
    this.panel = root.querySelector(".panel") as HTMLDivElement;
    this.badge = root.querySelector(".badge") as HTMLSpanElement;
    this.launcher.addEventListener("click", () => this.toggle());
    this.syncLauncher();
  }

  /**
   * The launcher takes the widget's own colour for the scheme in effect. A
   * host page's `--eneo-widget-color` still wins; see styles.
   */
  private paintLauncher(): void {
    const scheme = this.colors?.[this.effectiveScheme];
    if (scheme) {
      this.launcher.style.setProperty("--_eneo-accent", scheme.accent);
      this.launcher.style.setProperty("--_eneo-on-accent", scheme.on_accent);
    } else {
      this.launcher.style.removeProperty("--_eneo-accent");
      this.launcher.style.removeProperty("--_eneo-on-accent");
    }
  }

  private syncLauncher(): void {
    const custom = this.getAttribute("label");
    const label = this.isOpen
      ? this.labels.close
      : this.unread > 0
        ? this.labels.unread(this.unread)
        : custom || this.labels.open;
    this.launcher.setAttribute("aria-label", label);
    this.launcher.title = label;
    this.launcher.hidden = this.getAttribute("launcher") === "none";
    this.badge.hidden = this.unread === 0 || this.isOpen;
    this.badge.textContent = this.unread > 99 ? "99+" : String(this.unread);
  }

  private ensureFrame(): HTMLIFrameElement {
    if (this.frame) return this.frame;
    const frame = document.createElement("iframe");
    frame.title = this.getAttribute("frame-title") || this.labels.title;
    frame.setAttribute("sandbox", SANDBOX);
    frame.setAttribute("referrerpolicy", "strict-origin");
    frame.setAttribute("allow", "clipboard-write");
    frame.src = this.frameUrl;
    this.panel.appendChild(frame);
    this.frame = frame;
    return frame;
  }

  /** Load the iframe ahead of the first open, e.g. from `prefetch="true"`. */
  prefetch(): void {
    this.ensureFrame();
  }

  toggle(): void {
    if (this.isOpen) this.closePanel();
    else this.openPanel();
  }

  openPanel(): void {
    if (this.isOpen) return;
    if (this.closeTimer) {
      clearTimeout(this.closeTimer);
      this.closeTimer = null;
    }
    this.lastFocus = document.activeElement;
    this.isOpen = true;
    this.unread = 0;
    const frame = this.ensureFrame();
    this.setAttribute("open", "");
    this.launcher.setAttribute("aria-expanded", "true");
    this.syncLauncher();
    this.panel.hidden = false;
    if (reducedMotion()) this.panel.classList.add("open");
    else requestAnimationFrame(() => this.panel.classList.add("open"));
    this.watchViewport();
    this.fitViewport();
    if (this.frameReady) {
      this.send({ type: "open" });
      frame.focus();
    } else {
      this.pendingOpen = true;
    }
    this.emit("open");
  }

  closePanel(): void {
    if (!this.isOpen) return;
    this.isOpen = false;
    this.pendingOpen = false;
    this.removeAttribute("open");
    this.launcher.setAttribute("aria-expanded", "false");
    this.syncLauncher();
    this.panel.classList.remove("open");
    const hide = () => {
      this.closeTimer = null;
      this.panel.hidden = true;
    };
    if (reducedMotion()) hide();
    else this.closeTimer = setTimeout(hide, CLOSE_ANIMATION_MS);
    this.unwatchViewport();
    this.restoreFocus();
    this.emit("close");
  }

  private restoreFocus(): void {
    const target = this.launcher.hidden ? this.lastFocus : this.launcher;
    this.lastFocus = null;
    if (target instanceof HTMLElement && target.isConnected) target.focus();
  }

  /** Tell the assistant which page the visitor is on. Opt-in: nothing is sent unless the host asks. */
  setContext(context: PageContext): void {
    this.context = {
      page_url: typeof context.page_url === "string" ? context.page_url : undefined,
      page_title: typeof context.page_title === "string" ? context.page_title : undefined
    };
    this.send({ type: "context", payload: this.context });
  }

  private receive(event: MessageEvent): void {
    if (!this.frame || event.source !== this.frame.contentWindow) return;
    if (event.origin !== this.eneoOrigin) return;
    const message = parseFrameMessage(event.data);
    if (!message) return;
    switch (message.type) {
      case "ready":
        this.frameReady = true;
        this.colors = message.payload?.colors ?? null;
        this.paintLauncher();
        this.sendTheme();
        if (this.context) this.send({ type: "context", payload: this.context });
        if (this.pendingOpen) {
          this.pendingOpen = false;
          this.send({ type: "open" });
          this.frame.focus();
        }
        this.emit("ready");
        break;
      case "close":
        this.closePanel();
        break;
      case "unread":
        if (!this.isOpen) {
          this.unread = message.payload.count;
          this.syncLauncher();
        }
        this.emit("unread", message.payload);
        break;
      case "conversation_started":
        this.emit("conversation_started");
        break;
    }
  }

  private send(message: HostMessage): void {
    if (!this.frame || !this.frameReady) return;
    this.post(this.frame.contentWindow, envelope(message));
  }

  /** Seam for tests; the target is always the iframe's window. */
  protected post(target: Window | null, data: Record<string, unknown>): void {
    target?.postMessage(data, this.eneoOrigin);
  }

  private emit(name: WidgetEventName, detail?: unknown): void {
    this.dispatchEvent(
      new CustomEvent(EVENT_PREFIX + name, { detail, bubbles: true, composed: true })
    );
  }

  private watchViewport(): void {
    window.addEventListener("resize", this.onViewport);
    window.visualViewport?.addEventListener("resize", this.onViewport);
    window.visualViewport?.addEventListener("scroll", this.onViewport);
  }

  private unwatchViewport(): void {
    window.removeEventListener("resize", this.onViewport);
    window.visualViewport?.removeEventListener("resize", this.onViewport);
    window.visualViewport?.removeEventListener("scroll", this.onViewport);
    this.panel.style.height = "";
    this.panel.style.top = "";
  }

  /** Full-screen mode follows the visual viewport so the on-screen keyboard never covers the composer. */
  private fitViewport(): void {
    const viewport = window.visualViewport;
    if (!this.isOpen || !viewport || window.innerWidth >= MOBILE_BREAKPOINT) {
      this.panel.style.height = "";
      this.panel.style.top = "";
      return;
    }
    this.panel.style.height = `${viewport.height}px`;
    this.panel.style.top = `${viewport.offsetTop}px`;
  }
}
