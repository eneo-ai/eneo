/**
 * postMessage protocol between the loader (host page) and the embed page
 * (iframe). Mirrors `lib/features/widget/embedBridge.ts` in the web app; both
 * sides ignore anything outside the namespace or above their version.
 *
 * Pinned (SRI) copies of this loader live on customer sites for a long time,
 * so `BRIDGE_VERSION` is bumped only for changes an old side could misread.
 * New message types and optional payload fields keep the version: unknown
 * types are ignored and unknown fields dropped by the parsers on both sides.
 */

export const BRIDGE_NAMESPACE = "eneo-widget";
export const BRIDGE_VERSION = 1;

export type ColorScheme = "light" | "dark" | "auto";

export type PageContext = { page_url?: string; page_title?: string };

export type SchemeColors = { accent: string; on_accent: string };
/** What the launcher is painted with in each scheme; sent by the embed page with `ready`. */
export type LauncherColors = { light: SchemeColors; dark: SchemeColors };

const HEX = /^#[0-9a-f]{6}$/i;

function schemeColors(raw: unknown): SchemeColors | null {
  const value = raw as { accent?: unknown; on_accent?: unknown } | null;
  return value &&
    typeof value.accent === "string" &&
    HEX.test(value.accent) &&
    typeof value.on_accent === "string" &&
    HEX.test(value.on_accent)
    ? { accent: value.accent, on_accent: value.on_accent }
    : null;
}

export function parseLauncherColors(raw: unknown): LauncherColors | null {
  const value = raw as { light?: unknown; dark?: unknown } | null;
  const light = value ? schemeColors(value.light) : null;
  const dark = value ? schemeColors(value.dark) : null;
  return light && dark ? { light, dark } : null;
}

/** Messages the embed page sends to the loader. */
export type FrameMessage =
  | { type: "ready"; payload?: { colors: LauncherColors } }
  | { type: "close" }
  | { type: "conversation_started" }
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
    case "ready": {
      const colors = parseLauncherColors(payload.colors);
      return colors ? { type: "ready", payload: { colors } } : { type: "ready" };
    }
    case "close":
      return { type: "close" };
    case "conversation_started":
      // No payload by design: the host page never receives conversation ids.
      return { type: "conversation_started" };
    case "unread":
      return typeof payload.count === "number" && payload.count >= 0
        ? { type: "unread", payload: { count: Math.floor(payload.count) } }
        : null;
    default:
      return null;
  }
}
