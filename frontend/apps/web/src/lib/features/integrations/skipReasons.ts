import { m } from "$lib/paraglide/messages";

// The sync writes its skip reasons as the stable English strings defined in
// backend/src/eneo/integration/infrastructure/content_service/utils.py; this
// turns each one into the viewer's language. Unknown strings pass through.

const UNSUPPORTED_TYPE = /^Unsupported file type \((.+)\)$/s;
const NO_TEXT_LAYER = "No text layer (scanned document; OCR is not supported)";
const EMPTY_CONTENT = "Empty or unreadable content";
const FILE_TOO_LARGE = /^File too large \(exceeds (.+) MB limit\)$/;
const EXTRACTION_LIMIT = /^Exceeds extraction limit \((.+)\)$/s;
const LIMIT_TEXT_BYTES = /^(\d+) bytes of text$/;
const LIMIT_PDF_PAGES = /^(\d+) PDF pages$/;
const ERROR = /^Error: (.+)$/s;
const INCOMPLETE_DOWNLOAD = /^Incomplete download of '.*' \(\d+ of \d+ bytes\)$/s;
const PASSWORD_PROTECTED = "Password-protected file";
const CORRUPT_FILE = "Corrupt or malformed file";

function describeLimit(limit: string): string {
  const bytes = LIMIT_TEXT_BYTES.exec(limit);
  if (bytes) return m.skip_reason_limit_text_bytes({ count: Number(bytes[1]) });
  const pages = LIMIT_PDF_PAGES.exec(limit);
  if (pages) return m.skip_reason_limit_pdf_pages({ count: Number(pages[1]) });
  return limit;
}

function describeError(detail: string): string {
  if (INCOMPLETE_DOWNLOAD.test(detail)) return m.skip_reason_incomplete_download();
  if (detail === PASSWORD_PROTECTED) return m.skip_reason_password_protected();
  if (detail === CORRUPT_FILE) return m.skip_reason_corrupt_file();
  return m.skip_reason_error({ detail });
}

export type SkipReasonKind =
  | "unsupported_type"
  | "no_text_layer"
  | "empty_content"
  | "file_too_large"
  | "extraction_limit"
  | "incomplete_download"
  | "password_protected"
  | "corrupt_file"
  | "error";

/** Which of the sync's skip reasons a reason string is; anything unrecognised is an error. */
export function skipReasonKind(reason: string): SkipReasonKind {
  const trimmed = reason.trim();
  if (trimmed === NO_TEXT_LAYER) return "no_text_layer";
  if (trimmed === EMPTY_CONTENT) return "empty_content";
  if (UNSUPPORTED_TYPE.test(trimmed)) return "unsupported_type";
  if (FILE_TOO_LARGE.test(trimmed)) return "file_too_large";
  if (EXTRACTION_LIMIT.test(trimmed)) return "extraction_limit";
  const error = ERROR.exec(trimmed);
  if (error) {
    const detail = error[1];
    if (INCOMPLETE_DOWNLOAD.test(detail)) return "incomplete_download";
    if (detail === PASSWORD_PROTECTED) return "password_protected";
    if (detail === CORRUPT_FILE) return "corrupt_file";
  }
  return "error";
}

/** The reason a sync skipped a file, in the viewer's language. */
export function describeSkipReason(reason: string): string {
  const trimmed = reason.trim();
  if (trimmed === NO_TEXT_LAYER) return m.skip_reason_no_text_layer();
  if (trimmed === EMPTY_CONTENT) return m.skip_reason_empty_content();
  const unsupported = UNSUPPORTED_TYPE.exec(trimmed);
  if (unsupported) return m.skip_reason_unsupported_type({ label: unsupported[1] });
  const tooLarge = FILE_TOO_LARGE.exec(trimmed);
  if (tooLarge) return m.skip_reason_file_too_large({ limit: tooLarge[1] });
  const limit = EXTRACTION_LIMIT.exec(trimmed);
  if (limit) return m.skip_reason_extraction_limit({ limit: describeLimit(limit[1]) });
  const error = ERROR.exec(trimmed);
  if (error) return describeError(error[1]);
  return trimmed;
}
