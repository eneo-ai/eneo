/** Public docs keep English at existing URLs; Swedish is a sibling route. */
export function docsUrl(
  page: "guides/object-content-storage" | "guides/embed-widget",
  locale: string,
  anchor?: string
): string {
  const languagePrefix = locale === "sv" ? "/sv" : "";
  return `https://docs.eneo.ai${languagePrefix}/${page}${anchor ? `#${anchor}` : ""}`;
}
