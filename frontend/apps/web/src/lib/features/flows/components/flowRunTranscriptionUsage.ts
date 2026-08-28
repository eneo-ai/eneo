import type { FlowRunTranscriptionUsage } from "@eneo/eneo-js";

export type FlowRunTranscriptionUsagePayload = FlowRunTranscriptionUsage;

export interface FlowRunTranscriptionUsageRecordedView {
  kind: "recorded";
  /** What the badge shows: the recording's length when the step measured it. */
  audioSeconds: number;
  /** Audio sent to providers (a diarize-mode run sends the recording twice). */
  providerSeconds: number;
  /** True when `audioSeconds` is the measured recording rather than provider traffic. */
  measured: boolean;
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

  const providerSeconds = nonNegativeSeconds(transcriptionUsage.audio_seconds);
  const recording = transcriptionUsage.recording_seconds;
  const measured = typeof recording === "number" && Number.isFinite(recording) && recording > 0;
  return {
    kind: "recorded",
    audioSeconds: measured ? recording : providerSeconds,
    providerSeconds,
    measured,
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
