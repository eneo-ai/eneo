import { createTranslator } from "use-intl";
import { describe, expect, it } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import type { Schema } from "@/lib/api/models";
import { describeCheck } from "./transcription-service-check";

const t = createTranslator({ locale: "sv", messages }) as unknown as (
  key: string,
  values?: Record<string, string | number>
) => string;

const check = (
  overrides: Partial<Schema<"TranscriptionServiceLastCheckPublic">>
): Schema<"TranscriptionServiceLastCheckPublic"> => ({
  outcome: "ready",
  identifies_speakers: true,
  times_words: true,
  reason: null,
  status_code: null,
  service_version: null,
  checked_at: "2026-10-09T07:00:00Z",
  ...overrides
});

describe("describeCheck", () => {
  it("says what a ready service does for flows, with its version", () => {
    expect(describeCheck(check({ service_version: "2.4.1" }), t)).toEqual({
      tone: "success",
      label: t("speaker_service_status_ready"),
      detail: `${t("speaker_service_check_words_and_speakers")} ${t("speaker_service_check_version", { version: "2.4.1" })}`,
      note: t("speaker_service_note_words_and_speakers")
    });
    expect(describeCheck(check({ identifies_speakers: false }), t)).toMatchObject({
      tone: "success",
      detail: t("speaker_service_check_words_only"),
      note: t("speaker_service_note_words_only")
    });
  });

  it("warns when a service identifies speakers but gives no word timings: flows without speakers get text only", () => {
    expect(describeCheck(check({ times_words: false }), t)).toEqual({
      tone: "warning",
      label: t("speaker_service_status_no_words"),
      detail: t("speaker_service_check_no_words"),
      note: t("speaker_service_note_speakers_only")
    });
    expect(
      describeCheck(check({ times_words: false, identifies_speakers: false }), t)
    ).toMatchObject({ tone: "warning", label: t("speaker_service_status_no_tasks") });
  });

  it("stays neutral when a ready service does not say what it can do", () => {
    expect(describeCheck(check({ identifies_speakers: null, times_words: null }), t)).toEqual({
      tone: "info",
      label: t("speaker_service_status_ready"),
      detail: t("speaker_service_check_unknown_tasks"),
      note: null
    });
  });

  it("warns when the service is not accepting jobs", () => {
    expect(describeCheck(check({ outcome: "not_accepting_jobs" }), t)).toMatchObject({
      tone: "warning",
      label: t("speaker_service_status_not_accepting"),
      detail: t("speaker_service_check_not_accepting")
    });
  });

  it.each([
    {
      reason: "http_status" as const,
      status_code: 404,
      detail: t("speaker_service_check_http", { status: 404 }),
      note: t("speaker_service_note_http", { status: 404 })
    },
    {
      reason: "http_status" as const,
      status_code: 503,
      detail: t("speaker_service_check_not_ready"),
      note: t("speaker_service_note_http", { status: 503 })
    },
    {
      reason: "unreachable" as const,
      status_code: null,
      detail: t("speaker_service_check_unreachable"),
      note: t("speaker_service_note_unreachable")
    },
    {
      reason: "timeout" as const,
      status_code: null,
      detail: t("speaker_service_check_timeout"),
      note: t("speaker_service_note_timeout")
    },
    {
      reason: "malformed" as const,
      status_code: null,
      detail: t("speaker_service_check_malformed"),
      note: t("speaker_service_note_malformed")
    },
    { reason: null, status_code: null, detail: t("speaker_service_check_unavailable"), note: null }
  ])(
    "says why a service is unavailable ($reason $status_code) and where to look",
    ({ reason, status_code, detail, note }) => {
      expect(
        describeCheck(
          check({ outcome: "unavailable", identifies_speakers: null, reason, status_code }),
          t
        )
      ).toEqual({ tone: "error", label: t("speaker_service_status_unavailable"), detail, note });
    }
  );

  it("reports a rejected key as an error", () => {
    expect(
      describeCheck(check({ outcome: "credentials_rejected", reason: "credentials" }), t)
    ).toEqual({
      tone: "error",
      label: t("speaker_service_status_credentials"),
      detail: t("speaker_service_check_credentials"),
      note: null
    });
  });
});
