"use client";

import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";

/** A stored transcript segment, as the backend keeps it with a transcribe step. */
export type TranscriptSegment = {
  file_index?: number;
  start: number;
  end: number;
  speaker?: string | null;
  text: string;
  speaker_runs?: { char_start: number; char_end: number; speaker: string | null }[];
};

/** The transcription a transcribe step records with its input. */
export type StepTranscription = {
  segments?: TranscriptSegment[];
  speaker_names?: Record<string, string | null>;
  speaker_labels?: boolean;
  files_count?: number;
  audio_seconds?: number;
  language?: string | null;
};

/** `HH:MM:SS`, as the rendered transcript lines carry it. */
export function formatClock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const secs = whole % 60;
  return [hours, minutes, secs].map((part) => String(part).padStart(2, "0")).join(":");
}

export type TranscriptTurn = {
  speaker: string | null;
  start: number;
  end: number;
  lines: string[];
};

/** Consecutive segments of one speaker (in one file) folded into a turn. */
export function transcriptTurns(segments: readonly TranscriptSegment[]): TranscriptTurn[] {
  const turns: TranscriptTurn[] = [];
  let fileIndex: number | undefined;
  for (const segment of segments) {
    if (segment.speaker_runs?.length) {
      const characters = Array.from(segment.text);
      const pieces = segment.speaker_runs.map((run) => ({
        ...segment,
        speaker_runs: undefined,
        speaker: run.speaker,
        text: characters.slice(run.char_start, run.char_end).join("")
      }));
      turns.push(...transcriptTurns(pieces));
      fileIndex = undefined;
      continue;
    }
    const speaker = segment.speaker ?? null;
    const last = turns[turns.length - 1];
    if (last && last.speaker === speaker && fileIndex === (segment.file_index ?? 0)) {
      last.lines.push(segment.text);
      last.end = segment.end;
    } else {
      turns.push({ speaker, start: segment.start, end: segment.end, lines: [segment.text] });
      fileIndex = segment.file_index ?? 0;
    }
  }
  return turns;
}

const SPEAKER_TONES = [
  "text-ax-blue",
  "text-ax-teal",
  "text-ax-purple",
  "text-ax-orange",
  "text-ax-pink"
] as const;

/** One hue per speaker label, by order of appearance (decorative: the name carries it). */
export function speakerTone(label: string | null, order: readonly string[]): string {
  if (label === null) return "text-ax-text-secondary";
  const index = order.indexOf(label);
  return SPEAKER_TONES[(index < 0 ? 0 : index) % SPEAKER_TONES.length]!;
}

/**
 * A transcript as turns: who spoke (named when the mapping or a reviewer
 * named them, else the label), when, and what. Read-only; corrections are
 * made through the API.
 */
export function FlowTranscript({
  transcription,
  className
}: {
  transcription: StepTranscription;
  className?: string;
}) {
  const t = useTranslations();
  const segments = transcription.segments ?? [];
  const names = transcription.speaker_names ?? {};
  const turns = transcriptTurns(segments);
  const order = [...new Set(segments.flatMap((s) => (s.speaker ? [s.speaker] : [])))];
  if (turns.length === 0) {
    return <p className="text-ax-text-secondary m-0 text-[13px]">{t("flow_transcript_empty")}</p>;
  }
  return (
    <ol
      aria-label={t("flow_transcript_label")}
      className={cn("m-0 flex list-none flex-col gap-2 p-0", className)}
    >
      {turns.map((turn, index) => {
        const name = turn.speaker ? (names[turn.speaker] ?? turn.speaker) : null;
        return (
          <li key={index} className="flex flex-col gap-0.5">
            <span className="text-ax-text-secondary flex flex-wrap items-baseline gap-x-2 text-[11px] tabular-nums">
              <span>
                {formatClock(turn.start)} – {formatClock(turn.end)}
              </span>
              {name && (
                <span className={cn("font-semibold", speakerTone(turn.speaker, order))}>
                  {name}
                </span>
              )}
            </span>
            <p className="m-0 text-[13px] leading-snug whitespace-pre-wrap">
              {turn.lines.join(" ")}
            </p>
          </li>
        );
      })}
    </ol>
  );
}
