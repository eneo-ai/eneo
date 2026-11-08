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

export function personaView(config: WidgetPublicConfig, baseUrl: string): PersonaView | null {
  const persona = config.persona;
  const name = persona?.name;
  if (!name) return null;
  const avatarUrl = persona.avatar_icon_id ? avatarIconUrl(baseUrl, persona.avatar_icon_id) : null;
  return {
    name,
    avatarUrl,
    monogram: monogram(name),
    inLauncher: avatarUrl !== null && persona.avatar_in_launcher === true
  };
}

/** Icons are served by the backend, like `eneo.icons.url` in the app. */
export function avatarIconUrl(baseUrl: string, iconId: string): string {
  return `${new URL(baseUrl).origin}/api/v1/icons/${encodeURIComponent(iconId)}/`;
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
          .next().value?.segment ?? trimmed[0])
      : Array.from(trimmed)[0];
  return first.toLocaleUpperCase("sv");
}
