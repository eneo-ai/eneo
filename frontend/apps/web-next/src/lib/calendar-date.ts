/** Validate a date-input/URL calendar date without normalizing impossible dates. */
export function calendarDate(value: string | null | undefined): string | undefined {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return undefined;
  const instant = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(instant.getTime()) && instant.toISOString().slice(0, 10) === value
    ? value
    : undefined;
}

/** One formatter per locale and options: a chart formats hundreds of dates. */
const formatters = new Map<string, Intl.DateTimeFormat>();

/**
 * A calendar date (YYYY-MM-DD) in words, the same day in every time zone: it
 * is formatted as the UTC midnight it names, in UTC. Instants go through
 * ClientTime instead. An invalid date is returned as it is.
 */
export function formatCalendarDate(
  value: string,
  locale: string,
  options: Intl.DateTimeFormatOptions
): string {
  const date = calendarDate(value);
  if (!date) return value;
  // Bounded: callers pass fixed options, in one of the app's locales.
  const key = `${locale}|${JSON.stringify(options)}`;
  let formatter = formatters.get(key);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat(locale, { ...options, timeZone: "UTC" });
    formatters.set(key, formatter);
  }
  return formatter.format(new Date(`${date}T00:00:00Z`));
}
