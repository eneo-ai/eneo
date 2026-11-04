// A number as a reader expects to see it: with the noise of double arithmetic removed.
// 1607240.97 - 1678000 is -70759.03000000003 in doubles, 0.1 + 0.2 is 0.30000000000000004,
// and a sum over a few months of amounts lands at -70759.0299999998. The values the tools
// handle are amounts, counts and shares, which never carry fifteen significant digits of
// meaning, so a double is replaced by the shortest decimal within one part in 10^13 of it,
// at most fifteen digits. Thirteen digits are always kept, enough for öre on amounts up to
// a hundred billion; beyond that the figure reads as a spreadsheet would show it. The model
// copies the figures it gets into its answer, so this runs where values are produced, before
// the model, the result view and the CSV export see them, and the view applies it once more
// for stored results. Shared by the tools and the view kit, hence outside both.

/** The most significant digits a cleaned number keeps; a double carries no more dependably. */
export const SIGNIFICANT_DIGITS = 15;
/** How far, relative to the value, a shorter decimal may lie to count as the value itself. */
const RELATIVE_TOLERANCE = 1e-13;
/** A shortest representation of this many digits or fewer has no shorter decimal within the tolerance. */
const SHORT_DIGITS = 12;

/**
 * The shortest decimal within the tolerance of a finite fraction, at most fifteen significant
 * digits. An integer is returned as it is: up to 2^53 it is exact already, and beyond that
 * rounding could only move it further.
 */
export function cleanNumber(value: number): number {
  if (!Number.isFinite(value) || Number.isInteger(value)) return value;
  const shortest = value.toExponential();
  const digits = shortest.slice(0, shortest.indexOf("e")).replace(/[-.]/g, "").length;
  if (digits <= SHORT_DIGITS) return value;
  const tolerance = Math.abs(value) * RELATIVE_TOLERANCE;
  for (let precision = 1; precision < SIGNIFICANT_DIGITS; precision++) {
    const candidate = Number(value.toPrecision(precision));
    if (Math.abs(candidate - value) <= tolerance) return candidate;
  }
  return Number(value.toPrecision(SIGNIFICANT_DIGITS));
}

/**
 * A JSON value with every number in it cleaned. Strings are kept, including decimal strings
 * such as a Decimal result or a DuckDB DECIMAL, which are exact as written.
 */
export function cleanNumbers<T>(value: T): T {
  if (typeof value === "number") return cleanNumber(value) as T;
  if (Array.isArray(value)) return value.map(cleanNumbers) as T;
  if (value !== null && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value).map(([key, inner]) => [key, cleanNumbers(inner)]),
    ) as T;
  return value;
}
