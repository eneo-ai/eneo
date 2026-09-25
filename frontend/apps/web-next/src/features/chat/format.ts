/** Locale-aware formatting for the chat (durations, timestamps, token counts, greetings). */

function intlLocale(locale: string): string {
  return locale === "sv" ? "sv-SE" : locale === "en" ? "en-GB" : locale;
}

/** "14,6 s" in Swedish, "14.6 s" in English; sub-second values keep one decimal. */
export function formatSeconds(ms: number, locale: string): string {
  const seconds = Math.max(ms, 0) / 1000;
  const value = new Intl.NumberFormat(intlLocale(locale), {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1
  }).format(seconds);
  return `${value} s`;
}

/** "1 842" in Swedish (narrow no-break space grouping), "1,842" in English. */
export function formatCount(value: number, locale: string): string {
  return new Intl.NumberFormat(intlLocale(locale)).format(value);
}

export type DayRelation = "today" | "yesterday" | "earlier";

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

export function dayRelation(date: Date, now: Date): DayRelation {
  const diffDays = Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000);
  if (diffDays <= 0) return "today";
  if (diffDays === 1) return "yesterday";
  return "earlier";
}

/** Clock time ("09:42") for a message timestamp. */
export function formatClock(date: Date, locale: string): string {
  return new Intl.DateTimeFormat(intlLocale(locale), { hour: "2-digit", minute: "2-digit" }).format(
    date
  );
}

/** Short date ("12 sep.") for timestamps older than yesterday. */
export function formatShortDate(date: Date, now: Date, locale: string): string {
  return new Intl.DateTimeFormat(intlLocale(locale), {
    day: "numeric",
    month: "short",
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: "numeric" })
  }).format(date);
}

export type Greeting = "morning" | "day" | "evening";

/** God morgon (05–10), God dag (10–18), God kväll (otherwise). */
export function greetingFor(hour: number): Greeting {
  if (hour >= 5 && hour < 10) return "morning";
  if (hour >= 10 && hour < 18) return "day";
  return "evening";
}

/**
 * Name for the greeting. Users have no first-name field: a username with
 * spaces ("Anna Lind") gives its first word, otherwise the previous behaviour
 * applies (username, else the e-mail's local part, else the e-mail).
 */
export function firstNameOf(user: { username?: string | null; email: string }): string {
  const username = user.username?.trim();
  if (username) return username.split(/\s+/)[0] ?? username;
  return user.email.split("@")[0] || user.email;
}

/** History grouping buckets for the conversation list. */
export type HistoryBucket = "today" | "yesterday" | "week" | "month" | "older";

export function historyBucket(date: Date, now: Date): HistoryBucket {
  const diffDays = Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000);
  if (diffDays <= 0) return "today";
  if (diffDays === 1) return "yesterday";
  if (diffDays < 7) return "week";
  if (diffDays < 30) return "month";
  return "older";
}

/** "184 kB", "1,2 MB" (Swedish decimal comma): file sizes for attachment tokens. */
export function formatFileSize(bytes: number, locale: string): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "kB", "MB", "GB", "TB"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** exponent;
  const formatted = new Intl.NumberFormat(intlLocale(locale), {
    maximumFractionDigits: exponent <= 1 ? 0 : 1
  }).format(value);
  return `${formatted} ${units[exponent]}`;
}
