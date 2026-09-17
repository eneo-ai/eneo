/**
 * postMessage protocol between the loader (host page) and the embed page
 * (iframe). Mirrors `lib/features/widget/embedBridge.ts` in the web app; both
 * sides ignore anything outside the namespace or above their version.
 */

export const BRIDGE_NAMESPACE = "eneo-widget";
export const BRIDGE_VERSION = 1;

export type ColorScheme = "light" | "dark" | "auto";

export type PageContext = { page_url?: string; page_title?: string };

/** Messages the embed page sends to the loader. */
export type FrameMessage =
  | { type: "ready" }
  | { type: "close" }
  | { type: "conversation_started"; payload: { session_id: string } }
  | { type: "unread"; payload: { count: number } };

/** Messages the loader sends to the embed page. */
export type HostMessage =
  | { type: "open" }
  | { type: "theme"; payload: { scheme: ColorScheme } }
  | { type: "context"; payload: PageContext };

export function envelope(message: HostMessage): Record<string, unknown> {
  return { ns: BRIDGE_NAMESPACE, v: BRIDGE_VERSION, ...message };
}

export function parseFrameMessage(data: unknown): FrameMessage | null {
  if (!data || typeof data !== "object") return null;
  const raw = data as { ns?: unknown; v?: unknown; type?: unknown; payload?: unknown };
  if (raw.ns !== BRIDGE_NAMESPACE || typeof raw.v !== "number" || raw.v > BRIDGE_VERSION) {
    return null;
  }
  const payload = (raw.payload ?? {}) as Record<string, unknown>;
  switch (raw.type) {
    case "ready":
    case "close":
      return { type: raw.type };
    case "conversation_started":
      return typeof payload.session_id === "string"
        ? { type: "conversation_started", payload: { session_id: payload.session_id } }
        : null;
    case "unread":
      return typeof payload.count === "number" && payload.count >= 0
        ? { type: "unread", payload: { count: Math.floor(payload.count) } }
        : null;
    default:
      return null;
  }
}
