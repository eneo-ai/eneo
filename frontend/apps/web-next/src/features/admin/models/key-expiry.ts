/**
 * When a provider's API key runs out, as its card shows it. Admins enter the
 * date (few providers report it), so it is a calendar date rather than an
 * instant: the key is taken to work through that day.
 */

/** Days before the expiry date from which the card warns. */
export const KEY_EXPIRY_WARNING_DAYS = 30;

export type KeyExpiry = { state: "expiring" | "expired"; date: string };

const DAY_MS = 24 * 60 * 60 * 1000;

/** The viewer's calendar date as YYYY-MM-DD. */
export function localIsoDate(now: Date): string {
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** Days since the epoch; both dates at UTC midnight, so no DST hour sneaks in. */
function dayNumber(isoDate: string): number {
  return Math.round(Date.parse(`${isoDate}T00:00:00Z`) / DAY_MS);
}

/**
 * The notice for a key that expires on `expiresOn`, seen on `today`: a warning
 * from KEY_EXPIRY_WARNING_DAYS before through the expiry day, an error from
 * the day after, nothing before the window or without a date.
 */
export function keyExpiry(expiresOn: string | null | undefined, today: string): KeyExpiry | null {
  if (!expiresOn) return null;
  const daysLeft = dayNumber(expiresOn) - dayNumber(today);
  if (Number.isNaN(daysLeft)) return null;
  if (daysLeft < 0) return { state: "expired", date: expiresOn };
  if (daysLeft <= KEY_EXPIRY_WARNING_DAYS) return { state: "expiring", date: expiresOn };
  return null;
}
