import { intlLocale } from "./dateTime";

/** "A, B och C" in the UI language. */
export function formatList(items: readonly string[]): string {
  return new Intl.ListFormat(intlLocale(), { type: "conjunction" }).format(items);
}
