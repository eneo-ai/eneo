// Swedish formatting for the sandbox, which has no Intl: a space between thousands groups, a
// decimal comma, ISO dates. Written for QuickJS, so only the standard library is used.

type Numeric = number | string | { toString(): string };

/** A value as a plain decimal string ("-1234.5"), whatever numeric form it came in. */
function decimalString(value: Numeric): string {
  const text = typeof value === "number" ? numberToPlain(value) : String(value).trim();
  if (!/^-?\d+(\.\d+)?$/.test(text)) throw new TypeError(`fmt: not a number: ${text}`);
  return text;
}

/** A JavaScript number without exponent notation. */
function numberToPlain(value: number): string {
  if (!Number.isFinite(value)) throw new TypeError(`fmt: not a finite number: ${value}`);
  const text = String(value);
  if (!/e/i.test(text)) return text;
  const [mantissa, exponentText] = text.split(/e/i) as [string, string];
  const exponent = Number(exponentText);
  const negative = mantissa.startsWith("-");
  const digits = mantissa.replace("-", "").replace(".", "");
  const point = (mantissa.replace("-", "").split(".")[0] as string).length + exponent;
  let plain: string;
  if (point <= 0) plain = `0.${"0".repeat(-point)}${digits}`;
  else if (point >= digits.length) plain = digits + "0".repeat(point - digits.length);
  else plain = `${digits.slice(0, point)}.${digits.slice(point)}`;
  return (negative ? "-" : "") + plain;
}

/** Rounds a decimal string half away from zero to `decimals` places. */
function roundTo(text: string, decimals: number): string {
  const negative = text.startsWith("-");
  const [whole = "0", fraction = ""] = text.replace("-", "").split(".");
  if (fraction.length <= decimals) return (negative ? "-" : "") + whole + (decimals ? `.${fraction.padEnd(decimals, "0")}` : "");
  const kept = whole + fraction.slice(0, decimals);
  const next = fraction.charCodeAt(decimals) - 48;
  let digits = kept.split("").map((d) => d.charCodeAt(0) - 48);
  if (next >= 5) {
    let i = digits.length - 1;
    while (i >= 0) {
      if (digits[i] === 9) {
        digits[i] = 0;
        i--;
      } else {
        digits[i] = (digits[i] as number) + 1;
        break;
      }
    }
    if (i < 0) digits = [1, ...digits];
  }
  const all = digits.join("");
  const wholePart = all.slice(0, all.length - decimals) || "0";
  const fractionPart = all.slice(all.length - decimals);
  const result = wholePart + (decimals ? `.${fractionPart}` : "");
  return (negative && /[1-9]/.test(result) ? "-" : "") + result;
}

const GROUP = " ";

/**
 * A number the Swedish way: "1 234,50". `decimals` fixes the number of decimals (rounded half
 * away from zero); without it the value keeps its own decimals, at most ten, without trailing
 * zeros. The minus sign is ASCII so the text can be read back as a number.
 */
export function number(value: Numeric, options: { decimals?: number } = {}): string {
  let text = decimalString(value);
  if (options.decimals !== undefined) text = roundTo(text, Math.max(0, Math.min(20, options.decimals)));
  else {
    text = roundTo(text, 10).replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
  }
  const negative = text.startsWith("-");
  const [whole = "0", fraction] = text.replace("-", "").split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, GROUP);
  return (negative ? "-" : "") + grouped + (fraction ? `,${fraction}` : "");
}

/** A share as a percentage: fmt.percent(0.256) is "25,6 %". */
export function percent(value: Numeric, decimals = 1): string {
  const text = decimalString(value);
  const negative = text.startsWith("-");
  const [whole = "0", fraction = ""] = text.replace("-", "").split(".");
  const digits = whole + fraction.padEnd(2, "0");
  const scaled = `${digits.slice(0, digits.length - (fraction.length > 2 ? fraction.length - 2 : 0)) || "0"}${fraction.length > 2 ? `.${digits.slice(digits.length - (fraction.length - 2))}` : ""}`;
  return `${number((negative ? "-" : "") + scaled.replace(/^0+(?=\d)/, ""), { decimals })}${GROUP}%`;
}

function toDate(value: Date | string | number): Date {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) throw new TypeError(`fmt: not a date: ${String(value)}`);
  return date;
}
const pad = (n: number) => String(n).padStart(2, "0");

/** A date as YYYY-MM-DD, in UTC. */
export function date(value: Date | string | number): string {
  const d = toDate(value);
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
}

/** A date and time as YYYY-MM-DD HH:mm, in UTC. */
export function datetime(value: Date | string | number): string {
  const d = toDate(value);
  return `${date(d)} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}
