import type { FlowRunTranscriptionUsage } from "@eneo/eneo-js";

export type FlowRunTranscriptionUsagePayload = FlowRunTranscriptionUsage;

export interface FlowRunTranscriptionUsageRecordedView {
  kind: "recorded";
  audioSeconds: number;
  incomplete: boolean;
}

export type FlowRunTranscriptionUsageView =
  FlowRunTranscriptionUsageRecordedView | { kind: "not_recorded" };

export function buildFlowRunTranscriptionUsageView(
  transcriptionUsage: FlowRunTranscriptionUsagePayload | null | undefined
): FlowRunTranscriptionUsageView {
  if (!transcriptionUsage) {
    return { kind: "not_recorded" };
  }

  return {
    kind: "recorded",
    audioSeconds: nonNegativeSeconds(transcriptionUsage.audio_seconds),
    incomplete: transcriptionUsage.completeness === "incomplete"
  };
}

/** Reads as a duration, because seconds alone stop being legible after a few minutes. */
export function formatFlowRunAudioDuration(seconds: number): string {
  const whole = Math.round(seconds);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const remainder = whole % 60;
  const padded = (value: number) => String(value).padStart(2, "0");
  return hours > 0
    ? `${hours}:${padded(minutes)}:${padded(remainder)}`
    : `${minutes}:${padded(remainder)}`;
}

function nonNegativeSeconds(value: number | null | undefined): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0;
}
