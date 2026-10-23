// How a view shows a number, whatever tool the value came from: in the reader's locale, so a
// Swedish reader sees "120 924,67". A number arrives as a JSON number, or as a string when the
// script kept it exact: Decimal results and toFixed give "120924.67", a whole number too large
// for a JSON number arrives as its digits. A decimal string is shown as the number it is, with
// the decimals the script chose; a string of digits is left alone, since it is as often an
// identifier (a personnummer, a postcode) as a count.

/** A decimal number with a fraction, as Decimal and toFixed write it. */
const DECIMAL = /^-?\d+\.\d+$/;
/** A whole number as digits. */
const INTEGER = /^-?\d+$/;
/** Beyond this many significant digits a double cannot carry a string's value exactly. */
const EXACT_DIGITS = 15;
/** Intl's ceiling for fraction digits. */
const MAX_DECIMALS = 20;

/** Whether a cell is a number, for aligning a column on its figures. */
export const isNumeric = (value: unknown): boolean =>
  typeof value === "number" ||
  (typeof value === "string" && (DECIMAL.test(value) || INTEGER.test(value)));

/**
 * A formatter for one locale. Four-digit numbers keep their digits together (a year reads as
 * 2024, not 2 024); from five digits up they are grouped. Any other string is returned as it is.
 */
export function numberFormatter(locale: string | undefined): (value: number | string) => string {
  const tag = locale ?? "sv";
  const options: Intl.NumberFormatOptions = { useGrouping: "min2" };
  const plain = new Intl.NumberFormat(tag, { ...options, maximumFractionDigits: 10 });
  const fixed = new Map<number, Intl.NumberFormat>();
  return (value) => {
    if (typeof value === "number") return plain.format(value);
    if (!DECIMAL.test(value)) return value;
    const [whole = "", fraction = ""] = value.replace("-", "").split(".");
    const significant = (whole + fraction).replace(/^0+/, "").length;
    if (significant > EXACT_DIGITS || fraction.length > MAX_DECIMALS) return value;
    let format = fixed.get(fraction.length);
    if (!format) {
      format = new Intl.NumberFormat(tag, {
        ...options,
        minimumFractionDigits: fraction.length,
        maximumFractionDigits: fraction.length,
      });
      fixed.set(fraction.length, format);
    }
    return format.format(Number(value));
  };
}
