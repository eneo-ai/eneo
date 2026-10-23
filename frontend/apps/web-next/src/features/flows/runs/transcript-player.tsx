"use client";

import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { useHotkeys } from "@astryxdesign/core/hooks";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Kbd } from "@astryxdesign/core/Kbd";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Play, RotateCcw, RotateCw } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { refusalText } from "./run-messages";
import { inputFilePlayback, transcriptWordsQueryOptions } from "./runs-api";
import type { ShownSegment, TranscriptTarget } from "./transcript";
import {
  activeLine,
  activeWord,
  captionsFor,
  wordsByLine,
  type PlacedWord
} from "./transcript-playback";

export type Playback = {
  /**
   * Plays file `fileIndex` from `time` seconds, loading it first when
   * needed; stops at `until` seconds when given (a speaker's sample).
   */
  seek: (fileIndex: number, time: number, until?: number) => void;
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

/** The speeds the player offers; 1 is as recorded. */
export const PLAYBACK_RATES = [0.75, 1, 1.25, 1.5, 2] as const;
/** How far J and L skip, in seconds. */
export const SKIP_SECONDS = 10;
/** How far the skip buttons go, in seconds. */
export const NUDGE_SECONDS = 5;
/** A signed link is signed again this long before it runs out. */
export const RESIGN_LEAD_MS = 60_000;
/** Signed links last at most an hour; a later expiry is signed again daily, within what a timer holds. */
const RESIGN_MAX_DELAY_MS = 24 * 60 * 60 * 1000;

/** How long until a link that runs out at `expiresAt` (epoch ms) is signed again. */
export function resignDelay(expiresAt: number, now: number): number {
  return Math.min(RESIGN_MAX_DELAY_MS, Math.max(5_000, expiresAt - now - RESIGN_LEAD_MS));
}

/** How many placed words the aligner spread over their window instead of finding them. */
export function uncertainWordCount(words: ReadonlyMap<number, readonly PlacedWord[]>): number {
  let count = 0;
  for (const line of words.values()) for (const word of line) if (word.uncertain) count += 1;
  return count;
}

/**
 * Plays a transcript's audio with its lines: a click on a line, or on a word
 * where the transcription stored word timings, plays from there; the line
 * and word playing are marked, and the list follows playback unless the
 * person turns that off. The audio is the run's own input file, signed for
 * playback when it is first played (and again when the link has run out).
 * The marks are visual only: a screen reader is not told of every word.
 *
 * The speed can be changed, buttons skip five seconds either way and move
 * between the parts of a recording, and while focus is in the player J, K
 * and L skip back, play or pause, and skip forward (single letters a screen
 * reader's browse mode keeps for itself only reach the player in its focus
 * mode, so they never stand in for the controls). The signed link is signed
 * again a minute before it runs out, so a long listen does not stop.
 */
export function useTranscriptPlayback({
  flowId,
  runId,
  target,
  lines,
  sourceHash,
  eagerWords = false
}: {
  flowId: string;
  runId: string;
  target: TranscriptTarget;
  lines: readonly ShownSegment[];
  sourceHash: string;
  /** Reads the word timings before the audio plays, for a reviewer. */
  eagerWords?: boolean;
}): Playback | null {
  const t = useTranslations();
  const baseId = useId();
  const audio = useRef<HTMLAudioElement>(null);
  // Applied once the next file has its metadata, so a seek into a file that
  // is not loaded yet lands where the person clicked.
  const pending = useRef<number | null>(null);
  /** Whether the file goes on playing once it has loaded. */
  const pendingPlay = useRef(true);
  const resigned = useRef(false);
  const [file, setFile] = useState(0);
  const [src, setSrc] = useState<string | null>(null);
  const [expiresAt, setExpiresAt] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const [rate, setRate] = useState(1);
  const [focused, setFocused] = useState(false);
  const [position, setPosition] = useState({ line: -1, word: -1 });
  /** Where playback of the loaded file stops by itself (a sample); null to play on. */
  const stopAt = useRef<number | null>(null);
  const shortcutsId = `${baseId}-shortcuts`;
  const started = src !== null;
  const words = useQuery({
    ...transcriptWordsQueryOptions(flowId, runId, target.stepId),
    enabled: started || eagerWords
  });
  const placed = words.data ? wordsByLine(lines, words.data, sourceHash) : NO_WORDS;

  const lineId = (index: number) => `${baseId}-line-${index}`;
  const fileCount = target.fileIds.length;

  async function load(fileIndex: number, time: number, play = true) {
    const fileId = target.fileIds[fileIndex];
    if (!fileId) return;
    setLoading(true);
    setProblem(null);
    try {
      const signed = await inputFilePlayback(flowId, runId, fileId);
      pending.current = time;
      pendingPlay.current = play;
      setFile(fileIndex);
      setSrc(signed.path);
      setExpiresAt(signed.expiresAt);
    } catch (error) {
      setProblem(refusalText(error, t));
    } finally {
      setLoading(false);
    }
  }

  function seek(fileIndex: number, time: number, until?: number) {
    stopAt.current = until ?? null;
    const element = audio.current;
    if (!element || !src || fileIndex !== file) {
      void load(fileIndex, time);
      return;
    }
    element.currentTime = time;
    void element.play().catch(() => undefined);
  }

  function skip(seconds: number) {
    const element = audio.current;
    if (!element) return;
    const end = Number.isFinite(element.duration) ? element.duration : Infinity;
    element.currentTime = Math.min(end, Math.max(0, element.currentTime + seconds));
  }

  function toggle() {
    const element = audio.current;
    if (!element) return;
    if (element.paused) void element.play().catch(() => undefined);
    else element.pause();
  }

  /** Another part of the recording, from its start; it plays on when this one played. */
  function goToPart(fileIndex: number) {
    const element = audio.current;
    stopAt.current = null;
    void load(fileIndex, 0, element ? !element.paused : false);
  }

  // Signed again before the link runs out, where the person is, playing or not.
  const latestLoad = useRef(load);
  useEffect(() => {
    latestLoad.current = load;
  });
  useEffect(() => {
    if (!src || expiresAt === null) return;
    const timer = setTimeout(
      () => {
        const element = audio.current;
        void latestLoad.current(file, element?.currentTime ?? 0, element ? !element.paused : false);
      },
      resignDelay(expiresAt, Date.now())
    );
    return () => clearTimeout(timer);
  }, [src, expiresAt, file]);

  // The shortcuts listen only while focus is somewhere in the player.
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = box.current;
    if (!element) return;
    const enter = () => setFocused(true);
    const leave = (event: FocusEvent) => {
      if (!element.contains(event.relatedTarget as Node | null)) setFocused(false);
    };
    element.addEventListener("focusin", enter);
    element.addEventListener("focusout", leave);
    return () => {
      element.removeEventListener("focusin", enter);
      element.removeEventListener("focusout", leave);
    };
  }, []);

  useHotkeys([
    { keys: "j", onPress: () => skip(-SKIP_SECONDS), isDisabled: !focused || !src },
    { keys: "k", onPress: toggle, isDisabled: !focused || !src },
    { keys: "l", onPress: () => skip(SKIP_SECONDS), isDisabled: !focused || !src }
  ]);

  function track(element: HTMLAudioElement) {
    const time = element.currentTime;
    if (stopAt.current !== null && time >= stopAt.current) {
      stopAt.current = null;
      element.pause();
    }
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
    <div ref={box} className="flex flex-col gap-2">
      {problem ? (
        <Banner
          status="error"
          title={t("flow_transcript_audio_failed")}
          description={problem}
          collapsible={false}
        />
      ) : null}
      {src ? (
        <div
          role="group"
          aria-label={t("flow_transcript_player_label")}
          aria-describedby={shortcutsId}
          className="flex flex-col gap-2"
        >
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
              element.playbackRate = rate;
              resigned.current = false;
              if (pending.current !== null) {
                element.currentTime = pending.current;
                pending.current = null;
                if (pendingPlay.current) void element.play().catch(() => undefined);
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
          <div className="flex flex-wrap items-center gap-1">
            <IconButton
              label={t("flow_transcript_audio_back", { seconds: NUDGE_SECONDS })}
              icon={<RotateCcw aria-hidden="true" />}
              variant="ghost"
              size="sm"
              onClick={() => skip(-NUDGE_SECONDS)}
            />
            <IconButton
              label={t("flow_transcript_audio_forward", { seconds: NUDGE_SECONDS })}
              icon={<RotateCw aria-hidden="true" />}
              variant="ghost"
              size="sm"
              onClick={() => skip(NUDGE_SECONDS)}
            />
            {fileCount > 1 ? (
              <>
                <Button
                  label={t("flow_transcript_audio_previous_part")}
                  icon={<ChevronLeft aria-hidden="true" />}
                  variant="ghost"
                  size="sm"
                  isDisabled={file === 0}
                  onClick={() => goToPart(file - 1)}
                />
                <Button
                  label={t("flow_transcript_audio_next_part")}
                  endContent={<ChevronRight aria-hidden="true" />}
                  variant="ghost"
                  size="sm"
                  isDisabled={file + 1 >= fileCount}
                  onClick={() => goToPart(file + 1)}
                />
              </>
            ) : null}
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <Selector
              label={t("flow_transcript_audio_rate")}
              value={String(rate)}
              onChange={(value) => {
                const next = Number(value);
                if (!Number.isFinite(next)) return;
                setRate(next);
                if (audio.current) audio.current.playbackRate = next;
              }}
              options={PLAYBACK_RATES.map((value) => ({
                value: String(value),
                label: t("flow_transcript_audio_rate_value", { rate: value })
              }))}
              size="sm"
            />
            <CheckboxInput
              label={t("flow_transcript_audio_follow")}
              value={follow}
              onChange={setFollow}
              size="sm"
            />
          </div>
          <Text type="supporting" as="p" id={shortcutsId}>
            {t.rich("flow_transcript_audio_shortcuts", {
              j: () => <Kbd keys="j" />,
              k: () => <Kbd keys="k" />,
              l: () => <Kbd keys="l" />,
              seconds: SKIP_SECONDS
            })}
          </Text>
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
