/** Shared display formatting for dates, sizes and relative time. */

export function formatBytes(bytes: number, decimals = 1): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "kB", "MB", "GB", "TB"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** exponent;
  return `${value.toFixed(exponent === 0 ? 0 : decimals)} ${units[exponent]}`;
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
