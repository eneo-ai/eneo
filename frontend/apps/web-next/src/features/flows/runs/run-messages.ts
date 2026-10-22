import { EneoApiError, getErrorMessage } from "@/lib/api/errors";
import type { RunError } from "./runs-api";

/** next-intl's translator, as far as these messages use it. */
export type Translator = {
  (key: string, values?: Record<string, string | number>): string;
  has: (key: string) => boolean;
};

/** The catalog's sentence for a flow error code (`flow_error_<code>`), when it has one. */
export function flowErrorText(code: string | null | undefined, t: Translator): string | null {
  if (!code) return null;
  const key = `flow_error_${code}`;
  return t.has(key) ? t(key) : null;
}

/** A sentence the special codes need from their `context` or `details`. */
function contextualText(
  code: string | null | undefined,
  facts: Record<string, unknown>,
  t: Translator
): string | null {
  // A PDF refused because the server's text extraction was busy is a valid
  // file: the guidance is to wait and upload it again, not to split it.
  if (code === "flow_run_upload_pdf_exceeds_limit" && facts.reason === "extraction_capacity") {
    return t("flow_runs_refusal_pdf_extraction_busy");
  }
  if (code === "typed_io_speaker_service_unavailable") {
    if (facts.speaker_service_gap === "not_chosen") return t("flow_runs_speakers_not_chosen");
    if (facts.speaker_service_gap === "picked_unavailable") {
      return t("flow_runs_speakers_picked_unavailable");
    }
  }
  return null;
}

/**
 * A refused run request as a sentence the person can act on: the flow
 * catalog's text for the refusal's `code`, else the platform's text for its
 * error number, else the request's own message. The flow page's refusal
 * texts (`flow-refusals.ts`) cover the definition; these cover runs.
 */
export function refusalText(error: unknown, t: Translator): string {
  if (!(error instanceof EneoApiError)) return getErrorMessage(error, t);
  return (
    contextualText(error.reason, error.context ?? {}, t) ??
    flowErrorText(error.reason, t) ??
    getErrorMessage(error, t)
  );
}

/** Whether a refusal was about a revision someone else moved on (reload and try again). */
export function isStaleRefusal(error: unknown): boolean {
  return (
    error instanceof EneoApiError &&
    (error.reason === "flow_run_stale_version" ||
      error.reason === "flow_review_stale_revision" ||
      error.reason === "flow_transcript_corrections_stale_revision")
  );
}

/**
 * The catalog's sentence for a run's terminal error, refined by the facts
 * its `details` carry, or null when the catalog has none for its code.
 */
export function runErrorCatalogText(
  error: Pick<RunError, "code" | "details">,
  t: Translator
): string | null {
  return (
    contextualText(error.code, (error.details ?? {}) as Record<string, unknown>, t) ??
    flowErrorText(error.code, t)
  );
}

/**
 * A run's terminal error as a sentence: the catalog's text for its typed
 * `code`, refined by the facts its `details` carry. The run's own `message`
 * is technical detail for support, never the sentence shown.
 */
export function runErrorText(error: Pick<RunError, "code" | "details">, t: Translator): string {
  return runErrorCatalogText(error, t) ?? t("flow_runs_error_unknown");
}
