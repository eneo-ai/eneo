import { getLocale } from "$lib/paraglide/runtime";

type DateInput = string | number | Date | null | undefined;

export const DAY_MS = 24 * 60 * 60 * 1000;

/** The BCP 47 locale for `Intl` formatters that matches the UI language. */
export function intlLocale(): string {
  return getLocale() === "sv" ? "sv-SE" : "en-US";
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/** `YYYY-MM-DD` in local time, the date format used in tables and lists. Empty when unset. */
export function formatDate(value: DateInput): string {
  if (value == null) return "";
  const date = new Date(value);
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** `HH:mm` (or `HH:mm:ss`) in local time. */
export function formatTime(value: DateInput, { seconds = false } = {}): string {
  if (value == null) return "";
  const date = new Date(value);
  const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  return seconds ? `${time}:${pad(date.getSeconds())}` : time;
}

/** `YYYY-MM-DD HH:mm` (or with `:ss`) in local time. */
export function formatDateTime(value: DateInput, options: { seconds?: boolean } = {}): string {
  if (value == null) return "";
  return `${formatDate(value)} ${formatTime(value, options)}`;
}

/** A date written out for the UI language, e.g. "Sep 23, 2026" / "23 sep. 2026". */
export function formatDateMedium(value: DateInput): string {
  if (value == null) return "";
  return new Intl.DateTimeFormat(intlLocale(), { dateStyle: "medium" }).format(new Date(value));
}

const RELATIVE_UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 24 * 60 * 60],
  ["month", 30 * 24 * 60 * 60],
  ["week", 7 * 24 * 60 * 60],
  ["day", 24 * 60 * 60],
  ["hour", 60 * 60],
  ["minute", 60],
  ["second", 1]
];

/** "3 hours ago" / "för 3 timmar sedan", in the UI language. */
export function formatRelativeTime(
  value: DateInput,
  now: string | number | Date = Date.now()
): string {
  if (value == null) return "";
  const seconds = (new Date(value).getTime() - new Date(now).getTime()) / 1000;
  const formatter = new Intl.RelativeTimeFormat(intlLocale(), { numeric: "auto" });
  for (const [unit, size] of RELATIVE_UNITS) {
    if (Math.abs(seconds) >= size || unit === "second") {
      return formatter.format(Math.round(seconds / size), unit);
    }
  }
  return formatter.format(0, "second");
}

/** A duration in its largest whole unit, e.g. "5 minutes" / "5 minuter". */
export function formatDuration(milliseconds: number): string {
  const seconds = Math.abs(milliseconds) / 1000;
  const unit = (RELATIVE_UNITS.find(([, size]) => seconds >= size) ?? RELATIVE_UNITS.at(-1)!)[0];
  const size = RELATIVE_UNITS.find(([name]) => name === unit)![1];
  return new Intl.NumberFormat(intlLocale(), { style: "unit", unit, unitDisplay: "long" }).format(
    Math.round(seconds / size)
  );
}
