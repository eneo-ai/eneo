import type { TranscriptionServiceCheck } from "@eneo/eneo-js";
import { describe, expect, it } from "vitest";
import { m } from "$lib/paraglide/messages";
import { describeCheck } from "./transcriptionServiceCheck";

const check = (overrides: Partial<TranscriptionServiceCheck>): TranscriptionServiceCheck => ({
  outcome: "ready",
  detail: "",
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
    expect(describeCheck(check({ service_version: "2.4.1" }))).toEqual({
      tone: "positive",
      label: m.speaker_service_status_ready(),
      detail: `${m.speaker_service_check_words_and_speakers()} ${m.speaker_service_check_version({ version: "2.4.1" })}`,
      note: m.speaker_service_note_words_and_speakers()
    });
    expect(describeCheck(check({ identifies_speakers: false }))).toMatchObject({
      tone: "positive",
      detail: m.speaker_service_check_words_only(),
      note: m.speaker_service_note_words_only()
    });
  });

  it("warns when a service identifies speakers but gives no word timings: flows without speakers get text only", () => {
    expect(describeCheck(check({ times_words: false }))).toEqual({
      tone: "warning",
      label: m.speaker_service_status_no_words(),
      detail: m.speaker_service_check_no_words(),
      note: m.speaker_service_note_speakers_only()
    });
    expect(describeCheck(check({ times_words: false, identifies_speakers: false }))).toMatchObject({
      tone: "warning",
      label: m.speaker_service_status_no_tasks()
    });
  });

  it("stays neutral when a ready service does not say what it can do", () => {
    expect(describeCheck(check({ identifies_speakers: null, times_words: null }))).toEqual({
      tone: "info",
      label: m.speaker_service_status_ready(),
      detail: m.speaker_service_check_unknown_tasks(),
      note: null
    });
  });

  it("warns when the service is not accepting jobs", () => {
    expect(describeCheck(check({ outcome: "not_accepting_jobs" }))).toMatchObject({
      tone: "warning",
      label: m.speaker_service_status_not_accepting(),
      detail: m.speaker_service_check_not_accepting()
    });
  });

  it.each([
    {
      reason: "http_status" as const,
      status_code: 404,
      detail: m.speaker_service_check_http({ status: 404 }),
      note: m.speaker_service_note_http({ status: 404 })
    },
    {
      reason: "http_status" as const,
      status_code: 503,
      detail: m.speaker_service_check_not_ready(),
      note: m.speaker_service_note_http({ status: 503 })
    },
    {
      reason: "unreachable" as const,
      status_code: null,
      detail: m.speaker_service_check_unreachable(),
      note: m.speaker_service_note_unreachable()
    },
    {
      reason: "timeout" as const,
      status_code: null,
      detail: m.speaker_service_check_timeout(),
      note: m.speaker_service_note_timeout()
    },
    {
      reason: "malformed" as const,
      status_code: null,
      detail: m.speaker_service_check_malformed(),
      note: m.speaker_service_note_malformed()
    },
    {
      reason: null,
      status_code: null,
      detail: m.speaker_service_check_unavailable(),
      note: null
    }
  ])(
    "says why a service is unavailable ($reason $status_code) and where to look",
    ({ reason, status_code, detail, note }) => {
      expect(
        describeCheck(
          check({ outcome: "unavailable", identifies_speakers: null, reason, status_code })
        )
      ).toEqual({ tone: "negative", label: m.speaker_service_status_unavailable(), detail, note });
    }
  );

  it("reports a rejected key as an error", () => {
    expect(
      describeCheck(check({ outcome: "credentials_rejected", reason: "credentials" }))
    ).toEqual({
      tone: "negative",
      label: m.speaker_service_status_credentials(),
      detail: m.speaker_service_check_credentials(),
      note: null
    });
  });
});
