import type { Schema } from "@/lib/api/models";

type Translate = (key: string, values?: Record<string, string | number>) => string;

/** A Banner's status; the table's StatusLabel shows `info` as neutral. */
export type CheckTone = "success" | "info" | "warning" | "error";

/**
 * What a connection check means to an administrator: the short status the
 * table shows, the sentence the dialog adds, the tone both use, and a short
 * note for the table's second line (what the service does, or why it failed).
 */
export type CheckSummary = { tone: CheckTone; label: string; detail: string; note: string | null };

type Check = Pick<
  Schema<"TranscriptionServiceLastCheckPublic">,
  "outcome" | "identifies_speakers" | "times_words" | "service_version" | "reason" | "status_code"
>;

function withVersion(sentence: string, check: Check, t: Translate): string {
  return check.service_version
    ? `${sentence} ${t("speaker_service_check_version", { version: check.service_version })}`
    : sentence;
}

// A ready service is described by what it does for flows: word timings for
// every flow with the service, speakers for those that identify them.
function ready(check: Check, t: Translate): CheckSummary {
  const words = check.times_words;
  const speakers = check.identifies_speakers;
  const label = t("speaker_service_status_ready");
  if (words === null && speakers === null) {
    return { tone: "info", label, detail: t("speaker_service_check_unknown_tasks"), note: null };
  }
  if (words && speakers) {
    return {
      tone: "success",
      label,
      detail: withVersion(t("speaker_service_check_words_and_speakers"), check, t),
      note: t("speaker_service_note_words_and_speakers")
    };
  }
  if (words) {
    return {
      tone: "success",
      label,
      detail: withVersion(t("speaker_service_check_words_only"), check, t),
      note: t("speaker_service_note_words_only")
    };
  }
  if (speakers) {
    return {
      tone: "warning",
      label: t("speaker_service_status_no_words"),
      detail: t("speaker_service_check_no_words"),
      note: t("speaker_service_note_speakers_only")
    };
  }
  return {
    tone: "warning",
    label: t("speaker_service_status_no_tasks"),
    detail: t("speaker_service_check_no_tasks"),
    note: null
  };
}

// Why the service could not be used, said so the administrator knows where to look.
function unavailable(check: Check, t: Translate): CheckSummary {
  const failed = (detail: string, note: string | null): CheckSummary => ({
    tone: "error",
    label: t("speaker_service_status_unavailable"),
    detail,
    note
  });
  switch (check.reason) {
    case "http_status": {
      const status = check.status_code ?? 0;
      return failed(
        status === 503
          ? t("speaker_service_check_not_ready")
          : t("speaker_service_check_http", { status }),
        t("speaker_service_note_http", { status })
      );
    }
    case "unreachable":
      return failed(t("speaker_service_check_unreachable"), t("speaker_service_note_unreachable"));
    case "timeout":
      return failed(t("speaker_service_check_timeout"), t("speaker_service_note_timeout"));
    case "malformed":
      return failed(t("speaker_service_check_malformed"), t("speaker_service_note_malformed"));
    default:
      return failed(t("speaker_service_check_unavailable"), null);
  }
}

export function describeCheck(check: Check, t: Translate): CheckSummary {
  switch (check.outcome) {
    case "ready":
      return ready(check, t);
    case "not_accepting_jobs":
      return {
        tone: "warning",
        label: t("speaker_service_status_not_accepting"),
        detail: t("speaker_service_check_not_accepting"),
        note: null
      };
    case "unavailable":
      return unavailable(check, t);
    case "credentials_rejected":
      return {
        tone: "error",
        label: t("speaker_service_status_credentials"),
        detail: t("speaker_service_check_credentials"),
        note: null
      };
  }
}
