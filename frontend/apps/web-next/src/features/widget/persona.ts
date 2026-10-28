import type { WidgetPublicConfig } from "@eneo/eneo-js";

/**
 * The persona as the chat shows it: the configured name, the avatar's URL
 * when one was uploaded, and otherwise the letter that stands in for it.
 * Null when the widget has no persona; answers then carry no sender.
 */
export type PersonaView = {
  name: string;
  avatarUrl: string | null;
  monogram: string;
  /** The host page's launcher shows the avatar instead of the chat bubble. */
  inLauncher: boolean;
};

export function personaView(
  config: WidgetPublicConfig,
  appOrigin: string | null = null
): PersonaView | null {
  const persona = config.persona;
  const name = persona?.name;
  if (!name) return null;
  const avatarUrl = persona.avatar_icon_id
    ? avatarIconUrl(persona.avatar_icon_id, appOrigin)
    : null;
  return {
    name,
    avatarUrl,
    monogram: monogram(name),
    inLauncher: avatarUrl !== null && persona.avatar_in_launcher === true
  };
}

/**
 * Icons are public on the backend; the embed page reaches them through this
 * app's visitor proxy (src/app/api/v1/icons) under its own origin. Relative
 * on the page itself (whatever host it is served on); absolute, with the
 * app's origin, where another site reads it (the loader's launcher).
 */
export function avatarIconUrl(iconId: string, appOrigin: string | null = null): string {
  return `${appOrigin ?? ""}/api/v1/icons/${encodeURIComponent(iconId)}/`;
}

/** The first letter of the name, as one grapheme so "Åsa" and combined marks keep their shape. */
export function monogram(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "";
  const first =
    typeof Intl !== "undefined" && "Segmenter" in Intl
      ? (new Intl.Segmenter(undefined, { granularity: "grapheme" })
          .segment(trimmed)
          [Symbol.iterator]()
          .next().value?.segment ?? trimmed[0]!)
      : Array.from(trimmed)[0]!;
  return first.toLocaleUpperCase("sv");
}
