/**
 * postMessage protocol between the embed page (inside the iframe) and the
 * loader on the host page. Every message is origin-checked and carries no
 * secrets or identifiers.
 *
 * Versioning: a receiver ignores messages above its own version, and pinned
 * (SRI) loaders on customer sites can be years old. So `BRIDGE_VERSION` is
 * bumped only for changes an old receiver could misread; new message types
 * and new optional payload fields keep the version, since unknown types are
 * ignored and unknown fields are dropped by the parsers on both sides.
 */

export const BRIDGE_NAMESPACE = "eneo-widget";
export const BRIDGE_VERSION = 1;

import type { LauncherColors } from "./contrast";

export type OutboundMessage =
  | { type: "ready"; payload?: { colors?: LauncherColors; title?: string } }
  | { type: "close" }
  | { type: "conversation_started" }
  | { type: "unread"; payload: { count: number } };

export type InboundMessage =
  | { type: "open" }
  | { type: "theme"; payload: { scheme: "light" | "dark" | "auto" } }
  | { type: "context"; payload: { page_url?: string; page_title?: string } };

type Envelope<T> = { ns: typeof BRIDGE_NAMESPACE; v: number } & T;

export type EmbedBridgeHandlers = {
  onOpen?: () => void;
  onTheme?: (scheme: "light" | "dark" | "auto") => void;
  onContext?: (context: { page_url?: string; page_title?: string }) => void;
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
    default:
      return null;
  }
}

export function createEmbedBridge(options: {
  /** Origin of the host page; messages are only exchanged with it. */
  hostOrigin: string | null;
  handlers?: EmbedBridgeHandlers;
  target?: Pick<Window, "postMessage"> | null;
  addListener?: (listener: (event: MessageEvent) => void) => () => void;
}) {
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
    /**
     * The loader paints its launcher with the widget's colours and names the
     * frame after the widget's title for screen readers once the page is up.
     */
    ready: (colors?: LauncherColors, title?: string) =>
      post(
        colors || title
          ? {
              type: "ready",
              payload: { ...(colors ? { colors } : {}), ...(title ? { title } : {}) }
            }
          : { type: "ready" }
      ),
    close: () => post({ type: "close" }),
    /** The host only learns that a conversation began; the session id stays inside the frame. */
    conversationStarted: () => post({ type: "conversation_started" }),
    destroy: unsubscribe
  };
}
