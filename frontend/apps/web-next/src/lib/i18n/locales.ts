export const locales = ["sv", "en"] as const;
export type Locale = (typeof locales)[number];
export const defaultLocale: Locale = "sv";
export const LOCALE_COOKIE = "NEXT_LOCALE";

/** Each language in its own name, so every reader finds theirs (not translated). */
export const LOCALE_LABELS: Record<string, string> = { sv: "Svenska", en: "English" };

export function isLocale(value: unknown): value is Locale {
  return typeof value === "string" && (locales as readonly string[]).includes(value);
}
