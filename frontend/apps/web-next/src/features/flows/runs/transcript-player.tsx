"use client";

import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { Text } from "@astryxdesign/core/Text";
import { useQuery } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";
import { QuietBanner } from "@/components/astryx/banner";
import { refusalText } from "./run-messages";
import { inputFilePlaybackPath, transcriptWordsQueryOptions } from "./runs-api";
import type { ShownSegment, TranscriptTarget } from "./transcript";
import {
  activeLine,
  activeWord,
  captionsFor,
  wordsByLine,
  type PlacedWord
} from "./transcript-playback";

export type Playback = {
  /** Plays file `fileIndex` from `time` seconds, loading it first when needed. */
  seek: (fileIndex: number, time: number) => void;
  /** The line playing, by position in the lines, and its word; -1 for none. */
  activeLine: number;
  activeWord: number;
  words: ReadonlyMap<number, PlacedWord[]>;
  /** The id of the element that shows line `position`, for following playback. */
  lineId: (position: number) => string;
  /** The player above the lines. */
  player: React.ReactNode;
};

const NO_WORDS: ReadonlyMap<number, PlacedWord[]> = new Map();

/**
 * Plays a transcript's audio with its lines: a click on a line, or on a word
 * where the transcription stored word timings, plays from there; the line
 * and word playing are marked, and the list follows playback unless the
 * person turns that off. The audio is the run's own input file, signed for
 * playback when it is first played (and again when the link has run out).
 * The marks are visual only: a screen reader is not told of every word.
 */
export function useTranscriptPlayback({
  flowId,
  runId,
  target,
  lines,
  sourceHash
}: {
  flowId: string;
  runId: string;
  target: TranscriptTarget;
  lines: readonly ShownSegment[];
  sourceHash: string;
}): Playback | null {
  const t = useTranslations();
  const baseId = useId();
  const audio = useRef<HTMLAudioElement>(null);
  // Applied once the next file has its metadata, so a seek into a file that
  // is not loaded yet lands where the person clicked.
  const pending = useRef<number | null>(null);
  const resigned = useRef(false);
  const [file, setFile] = useState(0);
  const [src, setSrc] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const [position, setPosition] = useState({ line: -1, word: -1 });
  const started = src !== null;
  const words = useQuery({
    ...transcriptWordsQueryOptions(flowId, runId, target.stepId),
    enabled: started
  });
  const placed = words.data ? wordsByLine(lines, words.data, sourceHash) : NO_WORDS;

  const lineId = (index: number) => `${baseId}-line-${index}`;
  const fileCount = target.fileIds.length;

  async function load(fileIndex: number, time: number) {
    const fileId = target.fileIds[fileIndex];
    if (!fileId) return;
    setLoading(true);
    setProblem(null);
    try {
      const path = await inputFilePlaybackPath(flowId, runId, fileId);
      pending.current = time;
      setFile(fileIndex);
      setSrc(path);
    } catch (error) {
      setProblem(refusalText(error, t));
    } finally {
      setLoading(false);
    }
  }

  function seek(fileIndex: number, time: number) {
    const element = audio.current;
    if (!element || !src || fileIndex !== file) {
      void load(fileIndex, time);
      return;
    }
    element.currentTime = time;
    void element.play().catch(() => undefined);
  }

  function track(element: HTMLAudioElement) {
    const time = element.currentTime;
    const line = activeLine(lines, file, time);
    const own = line >= 0 ? placed.get(lines[line]!.index) : undefined;
    const word = own ? activeWord(own, time) : -1;
    if (line === position.line && word === position.word) return;
    setPosition({ line, word });
    if (follow && line !== position.line && line >= 0 && !element.paused) {
      const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      document
        .getElementById(lineId(line))
        ?.scrollIntoView({ block: "nearest", behavior: reduced ? "auto" : "smooth" });
    }
  }

  if (fileCount === 0) return null;

  const player = (
    <div className="flex flex-col gap-2">
      {problem ? (
        <QuietBanner
          status="error"
          title={t("flow_transcript_audio_failed")}
          description={problem}
          collapsible={false}
        />
      ) : null}
      {src ? (
        <div className="flex flex-col gap-2">
          {fileCount > 1 ? (
            <Text type="supporting">
              {t("flow_transcript_audio_part", { part: file + 1, count: fileCount })}
            </Text>
          ) : null}
          <audio
            ref={audio}
            src={src}
            controls
            preload="metadata"
            aria-label={
              fileCount > 1
                ? t("flow_transcript_audio_label_part", { part: file + 1 })
                : t("flow_transcript_audio_label")
            }
            className="w-full"
            onLoadedMetadata={(event) => {
              const element = event.currentTarget;
              resigned.current = false;
              if (pending.current !== null) {
                element.currentTime = pending.current;
                pending.current = null;
                void element.play().catch(() => undefined);
              }
            }}
            onTimeUpdate={(event) => track(event.currentTarget)}
            onSeeked={(event) => track(event.currentTarget)}
            onEnded={() => {
              // A recording in parts plays on into its next part.
              if (file + 1 < fileCount) void load(file + 1, 0);
            }}
            onError={(event) => {
              // A signed link that ran out: sign again once and go on where it was.
              if (resigned.current) {
                setProblem(t("flow_transcript_audio_unplayable"));
                return;
              }
              resigned.current = true;
              void load(file, event.currentTarget.currentTime || 0);
            }}
          >
            {/* The transcript is the audio's text: its lines are the captions too. */}
            <track
              kind="captions"
              label={t("flow_runs_transcript_heading")}
              src={`data:text/vtt;charset=utf-8,${encodeURIComponent(
                captionsFor(
                  lines,
                  file,
                  (position) =>
                    lines[position]?.name ??
                    lines[position]?.label ??
                    t("flow_runs_transcript_unknown_speaker")
                )
              )}`}
            />
            {t("flow_transcript_audio_unsupported")}
          </audio>
          <CheckboxInput
            label={t("flow_transcript_audio_follow")}
            value={follow}
            onChange={setFollow}
            size="sm"
          />
        </div>
      ) : (
        <div>
          <Button
            label={t("flow_transcript_audio_play")}
            icon={<Play aria-hidden="true" />}
            isLoading={loading}
            isInterruptible
            onClick={() => {
              if (!loading) void load(0, 0);
            }}
          />
        </div>
      )}
    </div>
  );

  return {
    seek,
    activeLine: position.line,
    activeWord: position.word,
    words: placed,
    lineId,
    player
  };
}
