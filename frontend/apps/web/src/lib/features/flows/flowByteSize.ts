/**
 * Format a byte count for the flow run dialog's file-size labels
 * (e.g. "Max 200 MB/fil", uploaded-file sizes).
 *
 * Base-1024, capped at GB. Shows one decimal only when the value is
 * below 10 in a scaled unit; whole numbers and raw bytes show none.
 * Non-finite and non-positive inputs collapse to "0 B".
 */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}
