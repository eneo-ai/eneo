// @ts-check
/** @typedef {import('./contrast.js').LauncherColors} LauncherColors */
/** @typedef {{ full: boolean; expanded: boolean }} PanelLayout */
/** @typedef {{ name: string; avatar_url: string | null }} LauncherPersona */
/** @typedef {| {
 * type: "ready";
 * payload?: { colors?: LauncherColors; title?: string; persona?: LauncherPersona };
 * }
 * | { type: "close" }
 * | { type: "conversation_started" }
 * | { type: "unread"; payload: { count: number } }
 * | { type: "expand" }
 * | { type: "collapse" }} OutboundMessage */
/** @typedef {| { type: "open" }
 * | { type: "theme"; payload: { scheme: "light" | "dark" | "auto" } }
 * | { type: "context"; payload: { page_url?: string; page_title?: string } }
 * | { type: "layout"; payload: PanelLayout }} InboundMessage */
/** @template T
 * @typedef {{ ns: typeof BRIDGE_NAMESPACE; v: number } & T} Envelope */
/** @typedef {{
 * onOpen?: () => void;
 * onTheme?: (scheme: "light" | "dark" | "auto") => void;
 * onContext?: (context: { page_url?: string; page_title?: string }) => void;
 * onLayout?: (layout: PanelLayout) => void;
 * }} EmbedBridgeHandlers */
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
/** Parse a raw message event payload into an inbound message, or null. */
/** @param {unknown} data
 * @returns {InboundMessage | null} */
export function parseInbound(data) {
  if (!data || typeof data !== "object") return null;
  const envelope = /** @type {Partial<Envelope<{ type?: unknown; payload?: unknown }>>} */ (data);
  if (envelope.ns !== BRIDGE_NAMESPACE) return null;
  if (typeof envelope.v !== "number" || envelope.v > BRIDGE_VERSION) return null;
  switch (envelope.type) {
    case "open":
      return { type: "open" };
    case "theme": {
      const scheme = /** @type {{ scheme?: unknown } | undefined} */ (envelope.payload)?.scheme;
      if (scheme === "light" || scheme === "dark" || scheme === "auto") {
        return { type: "theme", payload: { scheme } };
      }
      return null;
    }
    case "context": {
      const payload = /** @type {{ page_url?: unknown; page_title?: unknown }} */ (
        envelope.payload ?? {}
      );
      return {
        type: "context",
        payload: {
          page_url: typeof payload.page_url === "string" ? payload.page_url : undefined,
          page_title: typeof payload.page_title === "string" ? payload.page_title : undefined
        }
      };
    }
    case "layout": {
      const payload = /** @type {{ full?: unknown; expanded?: unknown }} */ (
        envelope.payload ?? {}
      );
      if (typeof payload.full !== "boolean" || typeof payload.expanded !== "boolean") return null;
      return { type: "layout", payload: { full: payload.full, expanded: payload.expanded } };
    }
    default:
      return null;
  }
}
/**
 * Origin and window checks are enforced before dispatching to the iframe UI.
 * @param {{hostOrigin: string | null, handlers?: EmbedBridgeHandlers,
 *   target?: Pick<Window, "postMessage"> | null,
 *   addListener?: (listener: (event: MessageEvent) => void) => () => void}} options
 */
export function createEmbedBridge(options) {
  const { hostOrigin, handlers = {} } = options;
  const embedded = typeof window !== "undefined" && window.parent !== window && hostOrigin !== null;
  const target = options.target ?? (embedded ? window.parent : null);
  /** @param {OutboundMessage} message
   * @returns {void} */
  function post(message) {
    if (!target || !hostOrigin) return;
    const envelope = {
      ns: BRIDGE_NAMESPACE,
      v: BRIDGE_VERSION,
      ...message
    };
    target.postMessage(envelope, hostOrigin);
  }
  /** @param {MessageEvent} event
   * @returns {void} */
  function listener(event) {
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
    /**
     * The loader paints its launcher with the widget's colours, names the
     * frame after the widget's title for screen readers once the page is up,
     * and names its button after the persona (showing its avatar when asked).
     */
    ready:
      /** @param {LauncherColors} [colors]
       * @param {string} [title]
       * @param {LauncherPersona} [persona] */ (colors, title, persona) =>
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
    /** Ask the loader to grow the panel over the host viewport, or to put it back. */
    expand: () => post({ type: "expand" }),
    collapse: () => post({ type: "collapse" }),
    /** The host only learns that a conversation began; the session id stays inside the frame. */
    conversationStarted: () => post({ type: "conversation_started" }),
    destroy: unsubscribe
  };
}

/** @typedef {ReturnType<typeof createEmbedBridge>} EmbedBridge */
