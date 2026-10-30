"use client";

import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import { CircleAlert, Play, Square } from "lucide-react";
import { useLocale, useTranslations } from "use-intl";
import { useEffect, useRef, useState } from "react";
import { formatBytes } from "@/lib/format";
import type { AudioRecorder, MicrophoneHint } from "./recorder";

type Translator = ReturnType<typeof useTranslations>;

export function micHintText(hint: MicrophoneHint, t: Translator): string {
  switch (hint) {
    case "muted":
      return t("flow_transcript_rec_mic_muted");
    case "reconnecting":
      return t("flow_transcript_rec_mic_reconnecting");
    case "silent":
      return t("flow_transcript_rec_mic_silent");
  }
}

/**
 * How loud the microphone is while recording, drawn every frame from the
 * recorder's analyser without rendering React. The bar is for the eye only:
 * what it means for the person (muted, nothing arriving, quiet) is said in
 * words beside it, and announced once.
 */
export function LevelMeter({
  recorder,
  hint
}: {
  recorder: AudioRecorder;
  hint: MicrophoneHint | null;
}) {
  const t = useTranslations();
  const fill = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    let frame = 0;
    let shown = 0;
    const draw = () => {
      const level = recorder.level() ?? 0;
      // Up quickly, down slowly, so speech reads as a steady bar.
      shown += (level - shown) * (level > shown ? 0.55 : 0.16);
      if (fill.current) fill.current.style.transform = `scaleX(${shown.toFixed(3)})`;
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [recorder]);

  if (!recorder.hasMeter && !hint) return null;
  return (
    <div className="flex flex-col gap-1">
      {recorder.hasMeter ? (
        <div className="flex items-center gap-2">
          <Text type="supporting">{t("flow_transcript_rec_mic_label")}</Text>
          <span
            aria-hidden="true"
            className="border-ax-border bg-ax-muted rounded-ax-inner block h-2 min-w-20 flex-1 overflow-hidden border"
          >
            <span
              ref={fill}
              className="bg-ax-accent block h-full origin-left motion-safe:transition-transform motion-safe:duration-75"
              style={{ transform: "scaleX(0)" }}
            />
          </span>
        </div>
      ) : null}
      {hint ? (
        <p className="text-ax-text m-0 flex items-start gap-1.5 text-sm">
          <CircleAlert className="text-ax-warning mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <span>{micHintText(hint, t)}</span>
        </p>
      ) : null}
    </div>
  );
}

/** The bytes an hour of recording takes at `bitsPerSecond`. */
export function bytesPerHour(bitsPerSecond: number): number {
  return (bitsPerSecond / 8) * 3_600;
}

/**
 * How large the part being recorded is so far, against the most one file
 * may be, and how much an hour of recording takes at this browser's bit
 * rate. Not a live region: it changes every second.
 */
export function RecordingSize({
  bytes,
  maxBytes,
  bitsPerSecond
}: {
  bytes: number;
  maxBytes: number | null;
  bitsPerSecond: number;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const size = formatBytes(bytes, locale);
  const rate = formatBytes(bytesPerHour(bitsPerSecond), locale);
  return (
    <Text type="supporting" as="p" className="tabular-nums">
      {maxBytes
        ? t("flow_transcript_rec_size_of_max", { size, max: formatBytes(maxBytes, locale), rate })
        : t("flow_transcript_rec_size", { size, rate })}
    </Text>
  );
}

/**
 * Plays one recorded part from its start. The media element is made here
 * and never rendered: a part just recorded has no captions to offer yet.
 */
class PartPlayer {
  #audio: HTMLAudioElement | null = null;

  async play(url: string, onEnd: () => void): Promise<void> {
    this.stop();
    const audio = new Audio(url);
    this.#audio = audio;
    audio.addEventListener("pause", onEnd);
    audio.addEventListener("ended", onEnd);
    await audio.play();
  }

  stop(): void {
    this.#audio?.pause();
    this.#audio = null;
  }
}

/**
 * The part recorded last, playable here before it has uploaded, so the
 * person can check that the microphone heard what it should. It plays from
 * its start and stops again on the same button, and stops by itself when
 * the preview goes away (a new recording starts).
 */
export function LastPartPreview({ url }: { url: string }) {
  const t = useTranslations();
  const [player] = useState(() => new PartPlayer());
  const [playing, setPlaying] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => () => player.stop(), [player, url]);

  async function toggle() {
    if (playing) {
      player.stop();
      return;
    }
    setFailed(false);
    try {
      await player.play(url, () => setPlaying(false));
      setPlaying(true);
    } catch {
      setFailed(true);
    }
  }

  return (
    <div className="flex flex-col gap-1">
      <div>
        <Button
          label={
            playing ? t("flow_transcript_rec_last_part_stop") : t("flow_transcript_rec_last_part")
          }
          icon={playing ? <Square aria-hidden="true" /> : <Play aria-hidden="true" />}
          size="sm"
          onClick={() => void toggle()}
        />
      </div>
      {failed ? (
        <Text type="supporting" as="p">
          {t("flow_transcript_rec_last_part_failed")}
        </Text>
      ) : null}
    </div>
  );
}
