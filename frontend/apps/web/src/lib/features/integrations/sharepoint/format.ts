import { getLocale } from "$lib/paraglide/runtime";

export function formatFileSize(bytes?: number): string {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatModifiedDate(dateStr?: string): string {
  if (!dateStr) return "";
  const date = new Date(dateStr);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(getLocale() === "sv" ? "sv-SE" : "en-US", {
    year: "numeric",
    month: "short",
    day: "numeric"
  });
}

export function formatDateTime(dateStr?: string | null): string {
  if (!dateStr) return "";
  const date = new Date(dateStr);
  if (Number.isNaN(date.getTime())) return dateStr;
  return new Intl.DateTimeFormat(getLocale() === "sv" ? "sv-SE" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(date);
}
