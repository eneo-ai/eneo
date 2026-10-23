// CSV is how a tool hands a table on: to the user as a download and to the next tool
// (create_chart, create_spreadsheet, create_document) as a source file, through Eneo's
// generated-file path rather than through the model's context.

/** An exported result travels as a file; Eneo admits generated files up to 20 MiB by default. */
export const MAX_EXPORT_BYTES = 20 * 1024 * 1024;

/** A download name for an exported result; never a path, always .csv. */
export function exportFilename(input: string | undefined, fallback = "resultat"): string {
  const base = (input ?? "")
    .normalize("NFC")
    .replace(/\.csv$/i, "")
    .replace(/[\u0000-\u001f\u007f-\u009f"\\/:;*?<>|]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^\.+/, "")
    .slice(0, 100)
    .trim();
  return `${base || fallback}.csv`;
}

/** RFC 4180 CSV; values are written exactly as the producer returned them. */
export function toCsv(columns: string[], rows: unknown[][]): string {
  const field = (value: unknown): string => {
    if (value === null || value === undefined) return "";
    const text = typeof value === "object" ? JSON.stringify(value) : String(value);
    return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
  };
  return [columns, ...rows].map((row) => row.map(field).join(",")).join("\r\n") + "\r\n";
}
