import type { components } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";

// The sync gives every skipped file a code with parameters (see
// backend/src/eneo/integration/domain/skip_reasons.py); this turns it into the
// viewer's language. The English `reason` is only shown for a code this client
// does not know.

export type SkipReasonCode = components["schemas"]["IntegrationSkippedDocument"]["code"];

export type SkipReason = {
  reason?: string | null;
  code?: SkipReasonCode | null;
  params?: Record<string, string | number>;
  retry?: boolean;
};

function text(params: SkipReason["params"], key: string): string {
  const value = params?.[key];
  return value === undefined || value === null ? "" : String(value);
}

function count(params: SkipReason["params"], key: string): number {
  return Number(params?.[key] ?? 0);
}

// The backend describes an error by its kind; these are the kinds it names.
const ERROR_DETAILS: Record<string, () => string> = {
  "Database error": m.skip_reason_detail_database,
  "Cache service error": m.skip_reason_detail_cache,
  "Connection error": m.skip_reason_detail_connection,
  "Request timed out": m.skip_reason_detail_timeout,
  "SharePoint offers no download for this item": m.skip_reason_detail_no_download
};
const HTTP_DETAIL = /^HTTP (\d{3})\b/;

/** An error detail in the viewer's language where the backend named its kind. */
export function describeErrorDetail(detail: string): string {
  const trimmed = detail.trim();
  const known = ERROR_DETAILS[trimmed];
  if (known) return known();
  const http = HTTP_DETAIL.exec(trimmed);
  if (http) return m.skip_reason_detail_http({ status: Number(http[1]) });
  return trimmed;
}

function describeHttp(params: SkipReason["params"]): string {
  const status = count(params, "status");
  if (status === 403) return m.skip_reason_http_forbidden();
  if (status === 404 || status === 410) return m.skip_reason_http_gone({ status });
  if (status === 429) return m.skip_reason_http_throttled();
  return m.skip_reason_http_other({ status });
}

function describeLimit(params: SkipReason["params"]): string {
  switch (text(params, "limit")) {
    case "text_bytes":
      return m.skip_reason_limit_text_bytes({ count: count(params, "value") });
    case "pdf_pages":
      return m.skip_reason_limit_pdf_pages({ count: count(params, "value") });
    case "resource":
      return m.skip_reason_limit_resource();
    case "deadline":
      return m.skip_reason_limit_deadline();
    case "output":
      return m.skip_reason_limit_output();
    default:
      return text(params, "detail");
  }
}

// The backend names unsupported types in English; the names without words pass through.
const TYPE_LABELS: Record<string, () => string> = {
  image: m.skip_reason_type_image,
  video: m.skip_reason_type_video,
  audio: m.skip_reason_type_audio,
  "legacy Word .doc, save as .docx": m.skip_reason_type_legacy_word,
  "legacy PowerPoint .ppt, save as .pptx": m.skip_reason_type_legacy_powerpoint,
  "rich text .rtf": m.skip_reason_type_rtf
};

function typeLabel(label: string): string {
  return Object.hasOwn(TYPE_LABELS, label) ? TYPE_LABELS[label]() : label;
}

const DESCRIPTIONS: Record<SkipReasonCode, (params: SkipReason["params"]) => string> = {
  unsupported_type: (p) => m.skip_reason_unsupported_type({ label: typeLabel(text(p, "label")) }),
  no_text_layer: () => m.skip_reason_no_text_layer(),
  empty_content: () => m.skip_reason_empty_content(),
  file_too_large: (p) => m.skip_reason_file_too_large({ limit: text(p, "limit_mb") }),
  extraction_limit: (p) => m.skip_reason_extraction_limit({ limit: describeLimit(p) }),
  incomplete_download: () => m.skip_reason_incomplete_download(),
  password_protected: () => m.skip_reason_password_protected(),
  corrupt_file: () => m.skip_reason_corrupt_file(),
  http_error: describeHttp,
  removal_failed: (p) =>
    m.skip_reason_removal_failed({ detail: describeErrorDetail(text(p, "detail")) }),
  listing_failed: (p) =>
    m.skip_reason_listing_failed({ detail: describeErrorDetail(text(p, "detail")) }),
  scope_path_unavailable: () => m.skip_reason_scope_path_unavailable(),
  missing_item_id: () => m.skip_reason_missing_item_id(),
  unchanged: () => m.skip_reason_unchanged(),
  set_aside: (p) =>
    m.skip_reason_set_aside({
      attempts: count(p, "attempts"),
      detail: describeErrorDetail(text(p, "detail"))
    }),
  error: (p) => m.skip_reason_error({ detail: describeErrorDetail(text(p, "detail")) })
};

/** Which of the sync's skip reasons this is; anything without a known code is an error. */
export function skipReasonKind(skip: SkipReason): SkipReasonCode {
  return skip.code && skip.code in DESCRIPTIONS ? skip.code : "error";
}

/** Why a sync skipped a file, in the viewer's language, with when it is tried again. */
export function describeSkipReason(skip: SkipReason): string {
  const describe = skip.code ? DESCRIPTIONS[skip.code] : undefined;
  const description = describe ? describe(skip.params) : (skip.reason ?? "").trim();
  // A set-aside file says itself when it is tried again: not at the next sync.
  if (!skip.retry || skip.code === "set_aside") return description;
  // The retry note is a sentence of its own; a reason ending in a full stop would double it.
  return m.skip_reason_with_retry({ reason: description.replace(/\.\s*$/, "") });
}
