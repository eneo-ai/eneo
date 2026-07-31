import { describe, expect, it, vi } from "vitest";

vi.mock("$lib/paraglide/messages", () => ({
  m: {
    job_failure_extraction_failed: () => "extraction_failed",
    job_failure_no_extractable_text: () => "no_extractable_text",
    job_failure_no_extractable_audio: () => "no_extractable_audio",
    job_failure_encrypted: () => "encrypted",
    job_failure_corrupt: () => "corrupt",
    job_failure_unsupported_format: () => "unsupported_format",
    job_failure_processing_failed: () => "processing_failed",
    job_failure_cancelled: () => "cancelled",
    job_failure_processing_interrupted: () => "processing_interrupted",
    job_failure_invalid_job_payload: () => "invalid_job_payload",
    job_failure_quota_exceeded: () => "quota_exceeded",
    job_failure_storage_limit_exceeded: () => "storage_limit_exceeded",
    job_failure_storage_unavailable: () => "storage_unavailable",
    job_failure_storage_verification_failed: () => "storage_verification_failed",
    job_failure_knowledge_source_conflict: () => "knowledge_source_conflict",
    job_failure_unknown: () => "unknown"
  }
}));

import { getJobFailureMessage } from "./getJobFailureMessage";

describe("getJobFailureMessage", () => {
  it.each([
    "extraction_failed",
    "no_extractable_text",
    "encrypted",
    "corrupt",
    "unsupported_format",
    "processing_failed",
    "cancelled",
    "processing_interrupted",
    "invalid_job_payload",
    "quota_exceeded",
    "storage_limit_exceeded",
    "storage_unavailable",
    "storage_verification_failed",
    "knowledge_source_conflict"
  ] as const)("maps %s to its localized recovery instruction", (code) => {
    expect(getJobFailureMessage(code, "upload_info_blob")).toBe(code);
  });

  it("uses audio-specific guidance when a transcription contains no speech", () => {
    expect(getJobFailureMessage("no_extractable_text", "transcription")).toBe(
      "no_extractable_audio"
    );
  });

  it.each([null, undefined, "future_failure_code"])(
    "uses the safe localized fallback for %s",
    (code) => {
      expect(getJobFailureMessage(code, "upload_info_blob")).toBe("unknown");
    }
  );
});
