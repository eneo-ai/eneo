// File names travel into a Content-Disposition header and a download link: sanitised once at
// creation and never derived from request input again.
import type { ExportFormat } from "./config";

export const MIME_BY_FORMAT: Record<ExportFormat, string> = {
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  pdf: "application/pdf",
};
export function safeFilename(input: string | undefined, format: ExportFormat): string {
  const base = (input ?? "")
    .normalize("NFC")
    .replace(/\.(docx|xlsx|pdf)$/i, "")
    .replace(/[\u0000-\u001f\u007f-\u009f"\\/:;*?<>|]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^\.+/, "")
    .slice(0, 100)
    .trim();
  return `${base || "dokument"}.${format}`;
}
/** RFC 6266 attachment disposition with an ASCII fallback and a UTF-8 `filename*`. */
export function contentDisposition(filename: string): string {
  const ascii = filename.replace(/[^\x20-\x7e]/g, "_").replace(/["\\]/g, "_");
  const encoded = encodeURIComponent(filename).replace(
    /[!'()*]/g,
    (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`,
  );
  return `attachment; filename="${ascii}"; filename*=UTF-8''${encoded}`;
}
