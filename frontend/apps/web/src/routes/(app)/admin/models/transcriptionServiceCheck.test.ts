import type { TranscriptionServiceCheck } from "@eneo/eneo-js";
import { describe, expect, it } from "vitest";
import { m } from "$lib/paraglide/messages";
import { describeCheck } from "./transcriptionServiceCheck";

const check = (overrides: Partial<TranscriptionServiceCheck>): TranscriptionServiceCheck => ({
  outcome: "ready",
  detail: "",
  identifies_speakers: true,
  service_version: null,
  checked_at: "2026-10-09T07:00:00Z",
  ...overrides
});

describe("describeCheck", () => {
  it("says a ready service identifies speakers, with its version", () => {
    expect(describeCheck(check({ service_version: "2.4.1" }))).toEqual({
      tone: "positive",
      label: m.speaker_service_status_ready(),
      detail: `${m.speaker_service_check_identifies()} ${m.speaker_service_check_version({ version: "2.4.1" })}`
    });
    expect(describeCheck(check({})).detail).toBe(m.speaker_service_check_identifies());
  });

  it("stays neutral when a ready service does not say what it can do", () => {
    expect(describeCheck(check({ identifies_speakers: null }))).toEqual({
      tone: "info",
      label: m.speaker_service_status_ready(),
      detail: m.speaker_service_check_unknown_tasks()
    });
  });

  it("warns when a ready service cannot identify speakers", () => {
    expect(describeCheck(check({ identifies_speakers: false }))).toEqual({
      tone: "warning",
      label: m.speaker_service_status_no_speakers(),
      detail: m.speaker_service_check_no_speakers()
    });
  });

  it("warns when the service is not accepting jobs", () => {
    expect(describeCheck(check({ outcome: "not_accepting_jobs" }))).toEqual({
      tone: "warning",
      label: m.speaker_service_status_not_accepting(),
      detail: m.speaker_service_check_not_accepting()
    });
  });

  it("reports an unreachable service as an error", () => {
    expect(describeCheck(check({ outcome: "unavailable", identifies_speakers: null }))).toEqual({
      tone: "negative",
      label: m.speaker_service_status_unavailable(),
      detail: m.speaker_service_check_unavailable()
    });
  });

  it("reports a rejected key as an error", () => {
    expect(describeCheck(check({ outcome: "credentials_rejected" }))).toEqual({
      tone: "negative",
      label: m.speaker_service_status_credentials(),
      detail: m.speaker_service_check_credentials()
    });
  });
});
