// Copyright (c) 2026 Sundsvalls Kommun

import type { TranscriptionServiceLastCheck } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";

export type CheckTone = "positive" | "info" | "warning" | "negative";

/** What a connection check means to an administrator: the short status the
 *  table shows, the sentence the dialog adds, and the tone both use. */
export type CheckSummary = { tone: CheckTone; label: string; detail: string };

export function describeCheck(check: TranscriptionServiceLastCheck): CheckSummary {
  switch (check.outcome) {
    case "ready":
      if (check.identifies_speakers === true) {
        const version = check.service_version
          ? ` ${m.speaker_service_check_version({ version: check.service_version })}`
          : "";
        return {
          tone: "positive",
          label: m.speaker_service_status_ready(),
          detail: `${m.speaker_service_check_identifies()}${version}`
        };
      }
      if (check.identifies_speakers === null) {
        return {
          tone: "info",
          label: m.speaker_service_status_ready(),
          detail: m.speaker_service_check_unknown_tasks()
        };
      }
      return {
        tone: "warning",
        label: m.speaker_service_status_no_speakers(),
        detail: m.speaker_service_check_no_speakers()
      };
    case "not_accepting_jobs":
      return {
        tone: "warning",
        label: m.speaker_service_status_not_accepting(),
        detail: m.speaker_service_check_not_accepting()
      };
    case "unavailable":
      return {
        tone: "negative",
        label: m.speaker_service_status_unavailable(),
        detail: m.speaker_service_check_unavailable()
      };
    case "credentials_rejected":
      return {
        tone: "negative",
        label: m.speaker_service_status_credentials(),
        detail: m.speaker_service_check_credentials()
      };
  }
}
