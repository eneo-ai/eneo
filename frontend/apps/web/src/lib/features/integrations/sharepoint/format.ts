import { formatBytes } from "$lib/core/formatting/formatBytes";
import { intlLocale } from "$lib/core/formatting/dateTime";

export function formatFileSize(bytes?: number): string {
  if (bytes == null) return "";
  return formatBytes(bytes, bytes >= 1024 * 1024 ? 1 : 0);
}

export function formatModifiedDate(dateStr?: string): string {
  if (!dateStr) return "";
  const date = new Date(dateStr);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(intlLocale(), {
    year: "numeric",
    month: "short",
    day: "numeric"
  });
}

export function formatDateTime(dateStr?: string | null): string {
  if (!dateStr) return "";
  const date = new Date(dateStr);
  if (Number.isNaN(date.getTime())) return dateStr;
  return new Intl.DateTimeFormat(intlLocale(), {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(date);
}
