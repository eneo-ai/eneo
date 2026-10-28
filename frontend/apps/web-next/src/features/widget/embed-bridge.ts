/**
 * postMessage protocol between the embed page (inside the iframe) and the
 * loader on the host page. Every message is origin-checked and carries no
 * secrets or identifiers. A port of apps/web's widget/embedBridge.ts: the
 * loader (packages/widget-loader) speaks one protocol to both apps.
 *
 * Versioning: a receiver ignores messages above its own version, and pinned
 * (SRI) loaders on customer sites can be years old. So `BRIDGE_VERSION` is
 * bumped only for changes an old receiver could misread; new message types
 * and new optional payload fields keep the version, since unknown types are
 * ignored and unknown fields are dropped by the parsers on both sides.
 */

import type { LauncherColors } from "./contrast";

export const BRIDGE_NAMESPACE = "eneo-widget";
export const BRIDGE_VERSION = 1;

/**
 * How the loader shows the panel right now. `full` is true whenever it covers
 * the host viewport: forced by a small screen, or because the chat asked to
 * expand. Loaders from before this message never send it, so the chat offers
 * its expand control only once a layout has arrived.
 */
export type PanelLayout = { full: boolean; expanded: boolean };

/**
 * The persona as the launcher needs it: the name for the button's accessible
 * name, the avatar only when the widget shows it as the launcher.
 */
export type LauncherPersona = { name: string; avatar_url: string | null };

export type OutboundMessage =
  | {
      type: "ready";
      payload?: { colors?: LauncherColors; title?: string; persona?: LauncherPersona };
    }
  | { type: "close" }
  | { type: "conversation_started" }
  | { type: "unread"; payload: { count: number } }
  | { type: "expand" }
  | { type: "collapse" };

export type Scheme = "light" | "dark" | "auto";

export type InboundMessage =
  | { type: "open" }
  | { type: "theme"; payload: { scheme: Scheme } }
  | { type: "context"; payload: { page_url?: string; page_title?: string } }
  | { type: "layout"; payload: PanelLayout };

type Envelope<T> = { ns: typeof BRIDGE_NAMESPACE; v: number } & T;

export type EmbedBridgeHandlers = {
  onOpen?: () => void;
  onTheme?: (scheme: Scheme) => void;
  onContext?: (context: { page_url?: string; page_title?: string }) => void;
  onLayout?: (layout: PanelLayout) => void;
};

/** Parse a raw message event payload into an inbound message, or null. */
export function parseInbound(data: unknown): InboundMessage | null {
  if (!data || typeof data !== "object") return null;
  const envelope = data as Partial<Envelope<{ type?: unknown; payload?: unknown }>>;
  if (envelope.ns !== BRIDGE_NAMESPACE) return null;
  if (typeof envelope.v !== "number" || envelope.v > BRIDGE_VERSION) return null;
  switch (envelope.type) {
    case "open":
      return { type: "open" };
    case "theme": {
      const scheme = (envelope.payload as { scheme?: unknown } | undefined)?.scheme;
      if (scheme === "light" || scheme === "dark" || scheme === "auto") {
        return { type: "theme", payload: { scheme } };
      }
      return null;
    }
    case "context": {
      const payload = (envelope.payload ?? {}) as { page_url?: unknown; page_title?: unknown };
      return {
        type: "context",
        payload: {
          page_url: typeof payload.page_url === "string" ? payload.page_url : undefined,
          page_title: typeof payload.page_title === "string" ? payload.page_title : undefined
        }
      };
    }
    case "layout": {
      const payload = (envelope.payload ?? {}) as { full?: unknown; expanded?: unknown };
      if (typeof payload.full !== "boolean" || typeof payload.expanded !== "boolean") return null;
      return { type: "layout", payload: { full: payload.full, expanded: payload.expanded } };
    }
    default:
      return null;
  }
}

export type EmbedBridge = {
  /** True inside the loader's iframe; false on the stand-alone page. */
  embedded: boolean;
  post: (message: OutboundMessage) => void;
  /**
   * The loader paints its launcher with the widget's colours, names the
   * frame after the widget's title for screen readers once the page is up,
   * and names its button after the persona (showing its avatar when asked).
   */
  ready: (colors?: LauncherColors, title?: string, persona?: LauncherPersona) => void;
  close: () => void;
  /** Ask the loader to grow the panel over the host viewport, or to put it back. */
  expand: () => void;
  collapse: () => void;
  /** The host only learns that a conversation began; the session id stays inside the frame. */
  conversationStarted: () => void;
  destroy: () => void;
};

export function createEmbedBridge(options: {
  /** Origin of the host page; messages are only exchanged with it. */
  hostOrigin: string | null;
  handlers?: EmbedBridgeHandlers;
  target?: Pick<Window, "postMessage"> | null;
  addListener?: (listener: (event: MessageEvent) => void) => () => void;
}): EmbedBridge {
  const { hostOrigin, handlers = {} } = options;
  const embedded = typeof window !== "undefined" && window.parent !== window && hostOrigin !== null;
  const target = options.target ?? (embedded ? window.parent : null);

  function post(message: OutboundMessage): void {
    if (!target || !hostOrigin) return;
    const envelope: Envelope<OutboundMessage> = {
      ns: BRIDGE_NAMESPACE,
      v: BRIDGE_VERSION,
      ...message
    };
    target.postMessage(envelope, hostOrigin);
  }

  function listener(event: MessageEvent): void {
    if (!hostOrigin || event.origin !== hostOrigin) return;
    if (target && event.source !== target) return;
    const message = parseInbound(event.data);
    if (!message) return;
    switch (message.type) {
      case "open":
        handlers.onOpen?.();
        break;
      case "theme":
        handlers.onTheme?.(message.payload.scheme);
        break;
      case "context":
        handlers.onContext?.(message.payload);
        break;
      case "layout":
        handlers.onLayout?.(message.payload);
        break;
    }
  }

  const unsubscribe =
    options.addListener?.(listener) ??
    (typeof window !== "undefined"
      ? (() => {
          window.addEventListener("message", listener);
          return () => window.removeEventListener("message", listener);
        })()
      : () => {});

  return {
    embedded,
    post,
    ready: (colors, title, persona) =>
      post(
        colors || title || persona
          ? {
              type: "ready",
              payload: {
                ...(colors ? { colors } : {}),
                ...(title ? { title } : {}),
                ...(persona ? { persona } : {})
              }
            }
          : { type: "ready" }
      ),
    close: () => post({ type: "close" }),
    expand: () => post({ type: "expand" }),
    collapse: () => post({ type: "collapse" }),
    conversationStarted: () => post({ type: "conversation_started" }),
    destroy: unsubscribe
  };
}
