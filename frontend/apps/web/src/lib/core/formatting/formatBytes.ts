/**
 * Format a size attribute in bytes as human-readable file size.
 * Uses base-1024 with conventional KB/MB/GB labels.
 * Returns "- Bytes" for negative values
 */
export function formatBytes(bytes: number, decimals = 0) {
  if (bytes < 0) return "- Bytes";
  if (!+bytes) return "0 Bytes";

  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ["Bytes", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB"];

  const i = Math.floor(Math.log(bytes) / Math.log(k));

  return `${(bytes / Math.pow(k, i)).toFixed(dm)} ${sizes[i]}`;
}
