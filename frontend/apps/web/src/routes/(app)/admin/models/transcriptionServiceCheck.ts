// Copyright (c) 2026 Sundsvalls Kommun

import type { TranscriptionServiceLastCheck } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";

export type CheckTone = "positive" | "info" | "warning" | "negative";

/** What a connection check means to an administrator: the short status the
 *  table shows, the sentence the dialog adds, the tone both use, and a short
 *  note for the table's second line (what the service does, or why it failed). */
export type CheckSummary = { tone: CheckTone; label: string; detail: string; note: string | null };

type Check = Pick<
  TranscriptionServiceLastCheck,
  "outcome" | "identifies_speakers" | "times_words" | "service_version" | "reason" | "status_code"
>;

function withVersion(sentence: string, check: Check): string {
  return check.service_version
    ? `${sentence} ${m.speaker_service_check_version({ version: check.service_version })}`
    : sentence;
}

// A ready service is described by what it does for flows: word timings for
// every flow with the service, speakers for those that identify them.
function ready(check: Check): CheckSummary {
  const words = check.times_words;
  const speakers = check.identifies_speakers;
  if (words === null && speakers === null) {
    return {
      tone: "info",
      label: m.speaker_service_status_ready(),
      detail: m.speaker_service_check_unknown_tasks(),
      note: null
    };
  }
  if (words && speakers) {
    return {
      tone: "positive",
      label: m.speaker_service_status_ready(),
      detail: withVersion(m.speaker_service_check_words_and_speakers(), check),
      note: m.speaker_service_note_words_and_speakers()
    };
  }
  if (words) {
    return {
      tone: "positive",
      label: m.speaker_service_status_ready(),
      detail: withVersion(m.speaker_service_check_words_only(), check),
      note: m.speaker_service_note_words_only()
    };
  }
  if (speakers) {
    return {
      tone: "warning",
      label: m.speaker_service_status_no_words(),
      detail: m.speaker_service_check_no_words(),
      note: m.speaker_service_note_speakers_only()
    };
  }
  return {
    tone: "warning",
    label: m.speaker_service_status_no_tasks(),
    detail: m.speaker_service_check_no_tasks(),
    note: null
  };
}

// Why the service could not be used, said so the administrator knows where to look.
function unavailable(check: Check): CheckSummary {
  const label = m.speaker_service_status_unavailable();
  switch (check.reason) {
    case "http_status":
      return check.status_code === 503
        ? {
            tone: "negative",
            label,
            detail: m.speaker_service_check_not_ready(),
            note: m.speaker_service_note_http({ status: 503 })
          }
        : {
            tone: "negative",
            label,
            detail: m.speaker_service_check_http({ status: check.status_code ?? 0 }),
            note: m.speaker_service_note_http({ status: check.status_code ?? 0 })
          };
    case "unreachable":
      return {
        tone: "negative",
        label,
        detail: m.speaker_service_check_unreachable(),
        note: m.speaker_service_note_unreachable()
      };
    case "timeout":
      return {
        tone: "negative",
        label,
        detail: m.speaker_service_check_timeout(),
        note: m.speaker_service_note_timeout()
      };
    case "malformed":
      return {
        tone: "negative",
        label,
        detail: m.speaker_service_check_malformed(),
        note: m.speaker_service_note_malformed()
      };
    default:
      return { tone: "negative", label, detail: m.speaker_service_check_unavailable(), note: null };
  }
}

export function describeCheck(check: Check): CheckSummary {
  switch (check.outcome) {
    case "ready":
      return ready(check);
    case "not_accepting_jobs":
      return {
        tone: "warning",
        label: m.speaker_service_status_not_accepting(),
        detail: m.speaker_service_check_not_accepting(),
        note: null
      };
    case "unavailable":
      return unavailable(check);
    case "credentials_rejected":
      return {
        tone: "negative",
        label: m.speaker_service_status_credentials(),
        detail: m.speaker_service_check_credentials(),
        note: null
      };
  }
}
