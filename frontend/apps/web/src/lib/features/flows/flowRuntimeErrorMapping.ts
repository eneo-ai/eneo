import { IntricError } from "@intric/intric-js";

const FLOW_SWEDISH_ERROR_BY_CODE: Record<string, string> = {
  flow_template_invalid_archive:
    "Den uppladdade filen är inte en giltig Word-mall (.docx). Välj en .docx-fil och försök igen.",
  flow_template_corrupted_archive:
    "Word-mallen verkar vara skadad. Prova att öppna och spara om filen i Word.",
  flow_template_macro_not_allowed:
    "Makroaktiverade Word-filer (.docm/.dotm) stöds inte som mallar. Spara filen som .docx och försök igen.",
  flow_template_missing_required_parts:
    "Filen ser inte ut att vara en giltig Word-mall. Kontrollera filen och försök igen.",
  flow_template_not_accessible: "Mallen är inte tillgänglig för dig i detta flow eller space.",
  flow_template_read_only: "Du kan använda flödet men inte byta mall för detta flow.",
  flow_template_unsupported_extension:
    "Endast .docx-filer kan användas som mall. Välj en .docx-fil och försök igen.",
  flow_template_missing_content:
    "Den valda DOCX-mallen kunde inte läsas eftersom filinnehållet saknas.",
  flow_run_rerun_step_inputs_unsupported:
    "Denna körning kan inte köras om med stegindata. Starta en ny körning i stället."
};

const UPLOAD_ERROR_HINTS: Record<string, string> = {
  timeout: " Försök igen med en mindre fil eller kontrollera din internetanslutning.",
  file_too_large: " Välj en mindre fil.",
  network: " Kontrollera din internetanslutning och försök igen."
};

export function classifyUploadError(message: string): "timeout" | "file_too_large" | "network" | "unknown" {
  const lower = message.toLowerCase();
  if (lower.includes("timeout") || lower.includes("timed out")) return "timeout";
  if (lower.includes("too large") || lower.includes("max") || lower.includes("storlek")) return "file_too_large";
  if (lower.includes("network") || lower.includes("fetch") || lower.includes("nät")) return "network";
  return "unknown";
}

export function getUploadErrorHint(errorKind: ReturnType<typeof classifyUploadError>): string {
  return UPLOAD_ERROR_HINTS[errorKind] ?? "";
}

const MISSING_TEMPLATE_CONTENT_PATTERNS = [
  "selected template file has no binary content",
  "published docx template file has no binary content",
  "file content is missing"
];

export function getFlowRuntimeErrorMessage(error: unknown, fallbackMessage: string): string {
  if (!(error instanceof IntricError)) {
    return fallbackMessage;
  }

  const responseCode =
    error.response &&
    typeof error.response === "object" &&
    !Array.isArray(error.response) &&
    typeof (error.response as { code?: unknown }).code === "string"
      ? (error.response as { code: string }).code
      : "";
  const code = typeof error.code === "string" ? error.code : responseCode;
  const mapped = getFlowRuntimeErrorMessageByCode(code);
  if (mapped) return mapped;

  const readable = error.getReadableMessage();
  const normalized = readable.toLowerCase();
  if (MISSING_TEMPLATE_CONTENT_PATTERNS.some((pattern) => normalized.includes(pattern))) {
    return FLOW_SWEDISH_ERROR_BY_CODE.flow_template_missing_content;
  }

  return readable;
}

export function getFlowRuntimeErrorMessageByCode(code: string | null | undefined): string | null {
  if (!code) return null;
  return FLOW_SWEDISH_ERROR_BY_CODE[code] ?? null;
}

const MIME_FRIENDLY_NAMES: Record<string, string> = {
  "application/pdf": "PDF",
  "application/msword": "Word",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word (.docx)",
  "application/vnd.ms-excel": "Excel",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel (.xlsx)",
  "application/vnd.ms-powerpoint": "PowerPoint",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint (.pptx)",
  "text/csv": "CSV",
  "text/plain": "Text",
  "text/html": "HTML",
  "text/markdown": "Markdown",
  "application/json": "JSON",
  "application/xml": "XML",
  "image/png": "PNG",
  "image/jpeg": "JPEG",
  "image/gif": "GIF",
  "image/webp": "WebP",
  "image/svg+xml": "SVG",
  "audio/mpeg": "MP3",
  "audio/wav": "WAV",
  "audio/ogg": "OGG",
  "audio/webm": "WebM (ljud)",
  "audio/mp4": "M4A",
  "video/mp4": "MP4",
  "video/webm": "WebM",
  "audio/*": "Ljudfiler",
  "video/*": "Videofiler",
  "image/*": "Bildfiler"
};

export function friendlyMimeNames(mimetypes: string[]): string[] {
  return mimetypes.map((mime) => MIME_FRIENDLY_NAMES[mime] ?? mime);
}
