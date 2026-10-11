import { getLocale } from "$lib/paraglide/runtime";

/** A count as the reader's language writes it ("1 000" or "1,000"). */
export function formatCount(count: number): string {
  return count.toLocaleString(getLocale());
}

/**
 * The sentence for a count. Exactly one has a sentence of its own ("1 fil",
 * never "1 filer"); every other number goes into the plural sentence, written
 * the way the reader's language writes numbers.
 */
export function countMessage(
  count: number,
  one: () => string,
  many: (inputs: { count: string }) => string
): string {
  return count === 1 ? one() : many({ count: formatCount(count) });
}
