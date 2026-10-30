import { formatBytes } from "@/lib/format";
import type { RunStep, RuntimeInput } from "./runs-api";

type Translate = (key: string, values?: Record<string, string | number>) => string;

/**
 * Names a person recognises for the file types a step takes; a type without
 * one keeps its MIME name. Several types share a name on purpose: a reader
 * picks a file by its ending, so "audio/mp4" and "audio/x-m4a" are both M4A.
 */
const TYPE_NAMES: Record<string, string> = {
  "application/pdf": "PDF",
  "application/msword": "Word (.doc)",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word (.docx)",
  "application/vnd.ms-excel": "Excel (.xls)",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel (.xlsx)",
  "application/vnd.ms-powerpoint": "PowerPoint (.ppt)",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint (.pptx)",
  "text/csv": "CSV",
  "application/csv": "CSV",
  "text/plain": "TXT",
  "text/html": "HTML",
  "text/markdown": "Markdown",
  "application/json": "JSON",
  "application/xml": "XML",
  "text/xml": "XML",
  "image/png": "PNG",
  "image/jpeg": "JPEG",
  "image/gif": "GIF",
  "image/webp": "WebP",
  "audio/mpeg": "MP3",
  "audio/mp3": "MP3",
  "audio/wav": "WAV",
  "audio/x-wav": "WAV",
  "audio/wave": "WAV",
  "audio/vnd.wave": "WAV",
  "audio/ogg": "OGG",
  "audio/webm": "WebM",
  "audio/mp4": "M4A",
  "audio/x-m4a": "M4A",
  "video/mp4": "MP4",
  "video/webm": "WebM"
};

export function typeNames(mimetypes: readonly string[]): string[] {
  return [...new Set(mimetypes.map((type) => TYPE_NAMES[type.toLowerCase()] ?? type))];
}

/** A file a step received: its name and type name where the core named it. */
export type StepInputFile = { fileId: string; name: string | null; typeName: string | null };

/**
 * The files a step received, in the order of `runtime_input_file_ids`, each
 * with the name and type the step result gives for it (none for a file the
 * core did not name).
 */
export function stepInputFiles(
  step: Pick<RunStep, "runtime_input_file_ids" | "runtime_input_files">
): StepInputFile[] {
  const named = new Map((step.runtime_input_files ?? []).map((file) => [file.file_id, file]));
  return (step.runtime_input_file_ids ?? []).map((fileId) => {
    const file = named.get(fileId);
    return {
      fileId,
      name: file?.name.trim() || null,
      typeName: file?.mimetype ? (typeNames([file.mimetype])[0] ?? null) : null
    };
  });
}

/** What a step takes, in one line: "PDF, Word (.docx) · högst 25 MB per fil · högst 3 filer". */
export function inputLimitsText(input: RuntimeInput, t: Translate, locale: string): string {
  const parts: string[] = [];
  const types = typeNames(input.accepted_mimetypes ?? []);
  if (types.length > 0) parts.push(types.join(", "));
  if (input.max_file_size_bytes != null) {
    parts.push(
      t("flow_runs_input_max_size", { size: formatBytes(input.max_file_size_bytes, locale) })
    );
  }
  if (input.max_files != null)
    parts.push(t("flow_runs_input_max_files", { count: input.max_files }));
  if (input.max_duration_seconds != null) {
    parts.push(
      t("flow_runs_input_max_duration", { minutes: Math.floor(input.max_duration_seconds / 60) })
    );
  }
  return parts.join(" · ");
}

/** A count of tokens in the reader's locale. */
export function formatCount(value: number, locale: string): string {
  return new Intl.NumberFormat(locale).format(value);
}

/** Seconds of audio as minutes and seconds: "12 min 5 s". */
export function formatSeconds(seconds: number, t: Translate): string {
  const whole = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return minutes > 0
    ? t("flow_runs_duration_minutes", { minutes, seconds: rest })
    : t("flow_runs_duration_seconds", { seconds: rest });
}
