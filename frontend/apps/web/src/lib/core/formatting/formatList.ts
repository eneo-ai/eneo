import { intlLocale } from "./dateTime";

/**
 * Items joined as a sentence list in the UI language ("A, B och C" / "A, B, and C").
 * `disjunction` joins with "eller" / "or". Never hand-join list items in copy.
 */
export function formatList(
  items: readonly string[],
  type: "conjunction" | "disjunction" = "conjunction"
): string {
  return new Intl.ListFormat(intlLocale(), { type }).format(items);
}
