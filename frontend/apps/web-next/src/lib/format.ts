/** Shared display formatting for sizes, dates and durations. */

const BYTE_UNITS = ["byte", "kilobyte", "megabyte", "gigabyte", "terabyte"] as const;

/**
 * A file or storage size in the given locale: "184 kB" and "1,2 MB" in
 * Swedish, "1.2 MB" in English. Steps of 1024, at most `maximumFractionDigits`
 * decimals above bytes (trailing zeros dropped).
 */
export function formatBytes(bytes: number, locale: string, maximumFractionDigits = 1): string {
  let value = Number.isFinite(bytes) && bytes > 0 ? bytes : 0;
  let exponent =
    value > 0 ? Math.min(Math.floor(Math.log(value) / Math.log(1024)), BYTE_UNITS.length - 1) : 0;
  value /= 1024 ** exponent;
  const digits = exponent === 0 ? 0 : maximumFractionDigits;
  // 1023.96 kB would round to "1 024 kB": show "1 MB" instead.
  if (exponent < BYTE_UNITS.length - 1 && Number(value.toFixed(digits)) >= 1024) {
    value /= 1024;
    exponent += 1;
  }
  return new Intl.NumberFormat(locale, {
    style: "unit",
    unit: BYTE_UNITS[exponent],
    unitDisplay: "short",
    maximumFractionDigits: exponent === 0 ? 0 : maximumFractionDigits
  }).format(value);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

const RELATIVE_STEPS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 1000 * 60 * 60 * 24 * 365],
  ["month", 1000 * 60 * 60 * 24 * 30],
  ["week", 1000 * 60 * 60 * 24 * 7],
  ["day", 1000 * 60 * 60 * 24],
  ["hour", 1000 * 60 * 60],
  ["minute", 1000 * 60]
];

/** "3 days ago" / "om 3 dagar" — between the given date and now. */
export function formatRelativeTime(value: string | Date, locale: string): string {
  const target = typeof value === "string" ? new Date(value) : value;
  const delta = target.getTime() - Date.now();
  const format = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  for (const [unit, ms] of RELATIVE_STEPS) {
    if (Math.abs(delta) >= ms) return format.format(Math.round(delta / ms), unit);
  }
  return format.format(Math.round(delta / 1000), "second");
}

/** Whole days elapsed since the given instant. */
export function daysSince(value: string | Date): number {
  const target = typeof value === "string" ? new Date(value) : value;
  return (Date.now() - target.getTime()) / (1000 * 60 * 60 * 24);
}

/** Hours from now until the given instant (negative when past). */
export function hoursUntil(value: string | Date): number {
  const target = typeof value === "string" ? new Date(value) : value;
  return (target.getTime() - Date.now()) / (1000 * 60 * 60);
}

/** Duration between two instants, in the largest sensible unit. */
export function formatDuration(start: string, end: string): string {
  const ms = Math.max(0, new Date(end).getTime() - new Date(start).getTime());
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.floor((ms % 60_000) / 1000);
  if (minutes >= 60) {
    const hours = Math.floor(minutes / 60);
    return `${hours} h ${minutes % 60} min`;
  }
  if (minutes > 0) return `${minutes} min ${seconds} s`;
  return `${seconds} s`;
}
