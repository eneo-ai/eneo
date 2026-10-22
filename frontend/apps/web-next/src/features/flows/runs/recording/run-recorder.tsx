"use client";

import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { ScrollableArea } from "@astryxdesign/core/ScrollableArea";
import { Heading } from "@astryxdesign/core/Heading";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Text } from "@astryxdesign/core/Text";
import { Timer } from "@astryxdesign/core/Timer";
import { Mic, Pause, Play, Square } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  useSyncExternalStore,
  type Ref
} from "react";
import { QuietBanner } from "@/components/astryx/banner";
import { EneoApiError } from "@/lib/api/errors";
import { useBeforeUnloadWarning } from "@/lib/hooks/use-before-unload-warning";
import type { RecordingPartInfo, UploadEntry } from "../run-contract";
import {
  liveSocketUrl,
  openLiveTranscription,
  type RunContract,
  type RuntimeInput
} from "../runs-api";
import { LiveTranscript, type LiveSnapshot } from "./live-transcript";
import {
  AudioRecorder,
  recordingSupport,
  browserEnvironment,
  type RecordedPart,
  type RecorderLimits,
  type RecorderProblem,
  type RecordingEnd
} from "./recorder";
import {
  clockText,
  lengthParts,
  recordingLimits,
  recordsInto,
  selectRecordingOptions
} from "./recording-format";

type Translator = ReturnType<typeof useTranslations>;

/** What the start form asks of a step's recorder, from its event handlers. */
export type RecorderHandle = {
  /** A recording runs, or its last part is on its way to the form. */
  busy: () => boolean;
  /** The live text's final text is still coming. */
  finishing: () => boolean;
  /** Settles once no final text is awaited. */
  settled: () => Promise<void>;
  /**
   * The core's stored live transcript, when the step's stored files (by
   * entry key) are exactly the one file of a recording the live text heard
   * whole.
   */
  liveTranscriptFor: (entryKeys: readonly string[]) => string | undefined;
};

/** "2 h 30 min", "45 min": a recording length as the form says it. */
export function lengthText(ms: number, t: Translator): string {
  const { hours, minutes } = lengthParts(ms);
  if (hours === 0) return t("flow_transcript_length_minutes", { minutes });
  if (minutes === 0) return t("flow_transcript_length_hours", { hours });
  return t("flow_transcript_length_hours_minutes", { hours, minutes });
}

function problemText(problem: RecorderProblem, t: Translator): string {
  switch (problem) {
    case "unsupported":
      return t("flow_transcript_rec_unsupported");
    case "insecure":
      return t("flow_transcript_rec_insecure");
    case "permission_denied":
      return t("flow_transcript_rec_permission_denied");
    case "no_microphone":
      return t("flow_transcript_rec_no_microphone");
    case "microphone_busy":
      return t("flow_transcript_rec_microphone_busy");
    case "microphone_failed":
      return t("flow_transcript_rec_microphone_failed");
  }
}

function endedText(ended: Exclude<RecordingEnd, "manual">, t: Translator): string {
  switch (ended) {
    case "length":
      return t("flow_transcript_rec_ended_length");
    case "files":
      return t("flow_transcript_rec_ended_files");
    case "device_lost":
      return t("flow_transcript_rec_ended_device_lost");
    case "error":
      return t("flow_transcript_rec_ended_error");
  }
}

/** Why the live text route refused, from its `context.reason`. */
function refusalReason(error: unknown): string {
  const reason = error instanceof EneoApiError ? error.context?.reason : undefined;
  return typeof reason === "string" ? reason : "unavailable";
}

/** Free file slots of a step: every file that did not fail takes one. */
function filesLeft(input: RuntimeInput, entries: readonly UploadEntry[]): number {
  if (input.max_files == null) return Infinity;
  return input.max_files - entries.filter((entry) => entry.state !== "failed").length;
}

/** The parts of a recording still on the form, in order. */
function partsOf(sessionId: string | null, entries: readonly UploadEntry[]) {
  if (!sessionId) return [];
  return entries.flatMap((entry) =>
    entry.recording?.sessionId === sessionId && entry.state !== "failed" ? [entry.recording] : []
  );
}

/**
 * The live text while recording: committed text, only ever appended, in a
 * region that scrolls with the keyboard. It is not a live region: a screen
 * reader would otherwise read every word of the meeting as it is spoken;
 * status changes are announced instead.
 */
function LiveText({ snapshot }: { snapshot: LiveSnapshot }) {
  const t = useTranslations();
  const { status, pieces, paused } = snapshot;
  const active = status === "connecting" || status === "listening" || status === "reconnecting";
  const hasText = pieces.length > 0;
  const ended = status === "interrupted" || status === "unavailable";
  if (!active && !ended && !(status === "finished" && hasText)) return null;
  const state =
    status === "connecting"
      ? t("flow_transcript_live_connecting")
      : status === "reconnecting"
        ? t("flow_transcript_live_reconnecting")
        : status === "listening"
          ? paused
            ? t("flow_transcript_rec_paused")
            : t("flow_transcript_live_listening")
          : null;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-3">
        <Heading level={4}>{t("flow_transcript_live_heading")}</Heading>
        {state ? <Text type="supporting">{state}</Text> : null}
      </div>
      {ended ? (
        <QuietBanner
          status="warning"
          title={
            status === "interrupted"
              ? t("flow_transcript_live_interrupted_title")
              : t("flow_transcript_live_unavailable_title")
          }
          description={
            status === "interrupted"
              ? t("flow_transcript_live_interrupted")
              : t("flow_transcript_live_unavailable")
          }
          collapsible={false}
        />
      ) : null}
      {active || hasText ? (
        <ScrollableArea
          axis="block"
          role="region"
          label={t("flow_transcript_live_heading")}
          className="border-ax-border-control bg-ax-surface text-ax-text focus-visible:outline-ring rounded-ax-inner max-h-56 border px-3 py-2 text-sm leading-relaxed focus-visible:outline-2 focus-visible:-outline-offset-2"
        >
          <p className="m-0">
            {hasText ? (
              pieces.map((piece) => <span key={piece.id}>{piece.text}</span>)
            ) : (
              <span className="text-ax-text-secondary">{t("flow_transcript_live_empty")}</span>
            )}
          </p>
        </ScrollableArea>
      ) : null}
      {status === "finished" ? (
        <Text type="supporting" as="p">
          {t("flow_transcript_live_draft")}
        </Text>
      ) : null}
    </div>
  );
}

/**
 * Records a step's audio with the device's microphone, as the step's files:
 * start, pause, go on and stop; a long recording goes on in parts at the
 * length the run contract asks for, and recording again after a stop
 * continues the same recording. Each part is added to the step's files when
 * it is done and uploads like a picked file.
 *
 * Where the flow's transcription model writes text in real time, the person
 * may follow a live draft of the text while recording. What keeps the
 * browser from recording (an insecure page, no recorder, a refused or busy
 * microphone) is said in plain words, with the upload as the way on.
 */
export function RunRecorder({
  flowId,
  input,
  live: liveOption,
  entries,
  onPart,
  handleRef
}: {
  flowId: string;
  input: RuntimeInput;
  live: NonNullable<RunContract["transcription"]>["live"] | undefined;
  entries: readonly UploadEntry[];
  /** Adds a finished part to the step's files and answers its entry key. */
  onPart: (file: File, recording: RecordingPartInfo, label: string) => string | undefined;
  handleRef?: Ref<RecorderHandle>;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const [support] = useState(() => recordingSupport(browserEnvironment()));
  const [options] = useState(() =>
    selectRecordingOptions((type) =>
      typeof MediaRecorder === "undefined" ? false : MediaRecorder.isTypeSupported(type)
    )
  );
  const liveAvailable = liveOption?.available === true;
  const [liveOn, setLiveOn] = useState(true);

  /** The step's files as of the last render, for limits read while recording. */
  const latestEntries = useRef(entries);
  /** The recording the step's recorded parts belong to. */
  const [session, setSession] = useState<string | null>(null);
  /** The entry of the last part the live text heard. */
  const liveEntry = useRef<string | null>(null);

  const [live] = useState(
    () =>
      new LiveTranscript({
        openSession: (recordingId) => openLiveTranscription(flowId, input.step_id, recordingId),
        socketUrl: (path) => liveSocketUrl(path),
        refusalReason
      })
  );
  const [recorder] = useState(() => new AudioRecorder(options));
  const liveWanted = liveAvailable && liveOn;

  useEffect(() => {
    latestEntries.current = entries;
    recorder.setCallbacks({
      onPart: (part: RecordedPart) => {
        const label = t("flow_transcript_rec_part_name", {
          part: part.index + 1,
          length: clockText(part.durationMs)
        });
        const key = onPart(
          part.file,
          { sessionId: part.sessionId, index: part.index, durationMs: part.durationMs },
          label
        );
        liveEntry.current = key ?? null;
      },
      onAudioGraph: (graph, signal) => {
        if (!graph) {
          live.stop();
          return;
        }
        // A new recording: whatever the live text showed belonged to the last one.
        if (!liveWanted) {
          live.discard();
          return;
        }
        return live.start(graph, signal);
      },
      onPause: (paused) => live.pause(paused),
      onRotate: () => live.lose()
    });
  });

  const snapshot = useSyncExternalStore(
    recorder.subscribe,
    recorder.getSnapshot,
    recorder.getSnapshot
  );
  const text = useSyncExternalStore(live.subscribe, live.getSnapshot, live.getSnapshot);

  useEffect(
    () => () => {
      recorder.dispose();
      live.discard();
    },
    [recorder, live]
  );

  const translate = useRef(t);
  useEffect(() => {
    translate.current = t;
  });

  // Status changes are announced politely; the clock and the words are not.
  useEffect(() => {
    let phase = recorder.getSnapshot().phase;
    let status = live.getSnapshot().status;
    const offRecorder = recorder.subscribe(() => {
      const next = recorder.getSnapshot();
      if (next.phase === phase) return;
      const message =
        next.phase === "recording"
          ? phase === "paused"
            ? "flow_transcript_rec_resumed_announce"
            : "flow_transcript_rec_started_announce"
          : next.phase === "paused"
            ? "flow_transcript_rec_paused_announce"
            : next.phase === "stopping"
              ? "flow_transcript_rec_stopped_announce"
              : null;
      phase = next.phase;
      if (message) announce(translate.current(message));
    });
    const offLive = live.subscribe(() => {
      const next = live.getSnapshot().status;
      if (next === status) return;
      const message =
        next === "reconnecting"
          ? "flow_transcript_live_lost_announce"
          : next === "listening" && status === "reconnecting"
            ? "flow_transcript_live_back_announce"
            : next === "interrupted"
              ? "flow_transcript_live_interrupted_title"
              : null;
      status = next;
      if (message) announce(translate.current(message));
    });
    return () => {
      offRecorder();
      offLive();
    };
  }, [recorder, live, announce]);

  useImperativeHandle(
    handleRef,
    () => ({
      busy: () => recorder.getSnapshot().phase !== "idle",
      finishing: () => live.getSnapshot().finishing,
      settled: () => live.settled(),
      liveTranscriptFor: (keys) => {
        const id = live.transcriptId;
        return id && keys.length === 1 && keys[0] === liveEntry.current ? id : undefined;
      }
    }),
    [recorder, live]
  );

  const recordedParts = entries.some((entry) => entry.recording);
  useBeforeUnloadWarning(snapshot.phase !== "idle" || recordedParts);

  const [filesFull, setFilesFull] = useState(false);
  const limits = recordingLimits(input, options.audioBitsPerSecond);

  function start() {
    if (snapshot.phase !== "idle") return;
    const left = filesLeft(input, entries);
    if (left < 1) {
      setFilesFull(true);
      return;
    }
    setFilesFull(false);
    const before = partsOf(session, entries);
    // Recording again while the last recording's parts are on the form goes on with it.
    const sessionId = before.length > 0 && session ? session : crypto.randomUUID();
    setSession(sessionId);
    const firstIndex = before.reduce((next, part) => Math.max(next, part.index + 1), 0);
    const recordedBeforeMs = before.reduce((sum, part) => sum + part.durationMs, 0);
    void recorder.start({
      sessionId,
      firstIndex,
      limits: (): RecorderLimits => ({
        ...limits,
        recordedBeforeMs,
        partsBefore: before.length,
        filesLeft: filesLeft(input, latestEntries.current)
      })
    });
  }

  if (!recordsInto(input, options.mimeType)) {
    return (
      <QuietBanner
        status="info"
        title={t("flow_transcript_rec_heading")}
        description={t("flow_transcript_rec_wrong_type")}
        collapsible={false}
      />
    );
  }

  if (support !== "supported") {
    return (
      <QuietBanner
        status="info"
        title={t("flow_transcript_rec_heading")}
        description={problemText(support, t)}
        collapsible={false}
      />
    );
  }

  const { phase, problem, ended } = snapshot;
  const continues = partsOf(session, entries).length > 0;
  const running = phase === "recording" || phase === "paused";
  return (
    <div className="border-ax-border rounded-ax-inner flex flex-col gap-3 border p-3">
      <div className="flex flex-col gap-1">
        <Heading level={4}>{t("flow_transcript_rec_heading")}</Heading>
        <Text type="supporting" as="p">
          {t("flow_transcript_rec_hint")}
          {limits.maxRecordingMs
            ? ` ${t("flow_transcript_rec_length_hint", { length: lengthText(limits.maxRecordingMs, t) })}`
            : null}
        </Text>
      </div>

      {problem ? (
        <QuietBanner
          status="error"
          title={t("flow_transcript_rec_problem_title")}
          description={problemText(problem, t)}
          collapsible={false}
        />
      ) : null}
      {filesFull ? (
        <QuietBanner
          status="warning"
          title={t("flow_transcript_rec_problem_title")}
          description={t("flow_transcript_rec_files_full", { count: input.max_files ?? 0 })}
          collapsible={false}
        />
      ) : null}
      {ended && ended !== "manual" && phase === "idle" ? (
        <QuietBanner
          status="warning"
          title={t("flow_transcript_rec_ended_title")}
          description={endedText(ended, t)}
          collapsible={false}
        />
      ) : null}

      {liveAvailable ? (
        <CheckboxInput
          label={t("flow_transcript_live_toggle")}
          description={t("flow_transcript_live_toggle_hint")}
          value={liveOn}
          onChange={setLiveOn}
          isDisabled={phase !== "idle"}
          size="sm"
        />
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        {phase === "idle" || phase === "starting" ? (
          <Button
            label={continues ? t("flow_transcript_rec_continue") : t("flow_transcript_rec_start")}
            icon={<Mic aria-hidden="true" />}
            variant="primary"
            isLoading={phase === "starting"}
            isInterruptible
            onClick={start}
          />
        ) : null}
        {phase === "recording" ? (
          <Button
            label={t("flow_transcript_rec_pause")}
            icon={<Pause aria-hidden="true" />}
            onClick={() => recorder.pause()}
          />
        ) : null}
        {phase === "paused" ? (
          <Button
            label={t("flow_transcript_rec_resume")}
            icon={<Play aria-hidden="true" />}
            onClick={() => recorder.resume()}
          />
        ) : null}
        {running ? (
          <Button
            label={t("flow_transcript_rec_stop")}
            icon={<Square aria-hidden="true" />}
            variant="destructive"
            onClick={() => void recorder.stop()}
          />
        ) : null}
        {phase === "starting" ? (
          <span className="text-ax-text-secondary text-sm">
            {t("flow_transcript_rec_starting")}
          </span>
        ) : null}
        {running ? (
          <span className="text-ax-text flex items-center gap-2 text-sm">
            <span className="font-medium">
              {phase === "recording"
                ? t("flow_transcript_rec_recording")
                : t("flow_transcript_rec_paused")}
            </span>
            {phase === "recording" && snapshot.clockStartedAt !== null ? (
              <Timer
                startTime={snapshot.clockStartedAt}
                format="clock"
                type="inherit"
                color="inherit"
                className="tabular-nums"
              />
            ) : (
              <span className="tabular-nums">{clockText(snapshot.recordedMs)}</span>
            )}
          </span>
        ) : null}
        {phase === "stopping" ? (
          <span className="text-ax-text-secondary text-sm">
            {t("flow_transcript_rec_stopping")}
          </span>
        ) : null}
        {running && snapshot.minutesLeft !== null ? (
          <span className="text-ax-text-secondary text-sm">
            {t("flow_transcript_rec_minutes_left", { count: snapshot.minutesLeft })}
          </span>
        ) : null}
      </div>

      <LiveText snapshot={text} />
    </div>
  );
}
