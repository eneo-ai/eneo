/** Locale-aware formatting for the chat (durations, greetings, history buckets). */

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

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
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
