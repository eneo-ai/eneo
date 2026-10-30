"use client";

import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { ScrollableArea } from "@astryxdesign/core/ScrollableArea";
import { Heading } from "@astryxdesign/core/Heading";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Text } from "@astryxdesign/core/Text";
import { Timer } from "@astryxdesign/core/Timer";
import { useQuery } from "@tanstack/react-query";
import { Mic, Pause, Play, Square } from "lucide-react";
import { useLocale, useTranslations } from "use-intl";
import {
  useEffect,
  useId,
  useImperativeHandle,
  useRef,
  useState,
  useSyncExternalStore,
  type Ref
} from "react";
import { flushSync } from "react-dom";
import { Banner } from "@astryxdesign/core/Banner";
import { EneoApiError } from "@/lib/api/errors";
import { formatBytes } from "@/lib/format";
import { useBeforeUnloadWarning } from "@/lib/hooks/use-before-unload-warning";
import type { RecordingPartInfo, UploadEntry } from "../run-contract";
import {
  liveSocketUrl,
  openLiveTranscription,
  type RunContract,
  type RuntimeInput
} from "../runs-api";
import { AutoRestart, type RestartOutcome } from "./auto-restart";
import { DiscardRecording } from "./discard-recording";
import { LiveTranscript, type LiveSnapshot } from "./live-transcript";
import {
  contractSnapshot,
  resumeRefusal,
  storedPartFile,
  type RecordingKeeper,
  type SavedRecording
} from "./recording-keeper";
import type { StoredPart } from "./recording-store";
import { resumeRefusalText, ResumePrompt } from "./resume-prompt";
import {
  AudioRecorder,
  MAX_PARTS_AWAITING_UPLOAD,
  recordingSupport,
  browserEnvironment,
  type MicrophoneHint,
  type RecordedPart,
  type RecorderLimits,
  type RecorderProblem,
  type RecordingEnd
} from "./recorder";
import { LastPartPreview, LevelMeter, micHintText, RecordingSize } from "./recorder-health";
import { partDiagnostics, RecordingDiagnostics, recordingReport } from "./recording-diagnostics";
import {
  clockText,
  lengthParts,
  recordingLimits,
  recordingTimeLeftMs,
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
    case "backlog":
      return t("flow_transcript_rec_ended_backlog");
    case "device_lost":
      return t("flow_transcript_rec_ended_device_lost");
    case "stall":
      return t("flow_transcript_rec_ended_stall");
    case "error":
      return t("flow_transcript_rec_ended_error");
  }
}

/** The ends a recording may start again from by itself: the microphone was lost. */
const LOST: ReadonlySet<RecordingEnd> = new Set(["device_lost", "stall", "error"]);

function restartingText(ended: RecordingEnd | null, t: Translator): string {
  switch (ended) {
    case "stall":
      return t("flow_transcript_rec_restarting_stall");
    case "error":
      return t("flow_transcript_rec_restarting_error");
    default:
      return t("flow_transcript_rec_restarting_device_lost");
  }
}

/** The step's recorded parts not uploaded yet, a failed part that will be sent again included. */
function awaitingUpload(entries: readonly UploadEntry[]): number {
  return entries.filter(
    (entry) =>
      entry.recording &&
      (entry.state === "uploading" || (entry.state === "failed" && entry.retryable))
  ).length;
}

/** Why the live text route refused, from its `context.reason`. */
function refusalReason(error: unknown): string {
  const reason = error instanceof EneoApiError ? error.context?.reason : undefined;
  return typeof reason === "string" ? reason : "unavailable";
}

/**
 * Whether a file stays on the form: one that did not fail, or a recorded
 * part whose upload will be sent again (it exists nowhere else).
 */
function stays(entry: UploadEntry): boolean {
  return entry.state !== "failed" || Boolean(entry.recording && entry.retryable);
}

/** Free file slots of a step: every file that stays takes one. */
function filesLeft(input: RuntimeInput, entries: readonly UploadEntry[]): number {
  if (input.max_files == null) return Infinity;
  return input.max_files - entries.filter(stays).length;
}

/** The recording the step's last recorded part belongs to, which recording again continues. */
function latestSession(entries: readonly UploadEntry[]): string | null {
  return entries.findLast((entry) => entry.recording && stays(entry))?.recording?.sessionId ?? null;
}

/** The parts of a recording still on the form, in order. */
function partsOf(sessionId: string | null, entries: readonly UploadEntry[]) {
  if (!sessionId) return [];
  return entries.flatMap((entry) =>
    entry.recording?.sessionId === sessionId && stays(entry) ? [entry.recording] : []
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
        <Banner
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
  keeper,
  publishedFlowVersion,
  onSaveForLater,
  onDiscard,
  handleRef
}: {
  flowId: string;
  input: RuntimeInput;
  live: NonNullable<RunContract["transcription"]>["live"] | undefined;
  entries: readonly UploadEntry[];
  /** Adds a finished part to the step's files and answers its entry key. */
  onPart: (file: File, recording: RecordingPartInfo, label: string) => string | undefined;
  /** Keeps the form's recordings on the device, and finds those kept before. */
  keeper: RecordingKeeper;
  /** The published version the run contract describes, kept with each part. */
  publishedFlowVersion: number | null;
  /** Closes the form and keeps the recording on the device to continue later. */
  onSaveForLater?: () => void;
  /** Takes the step's recorded parts (by entry key) off the form, stopping or deleting their uploads. */
  onDiscard?: (keys: readonly string[]) => void;
  handleRef?: Ref<RecorderHandle>;
}) {
  const t = useTranslations();
  const locale = useLocale();
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
  const translate = useRef(t);
  useEffect(() => {
    translate.current = t;
  });
  /** The part recorded last, playable before it has uploaded. */
  const [lastPart, setLastPart] = useState<{ key: string; url: string } | null>(null);
  const lastPartUrl = useRef<string | null>(null);
  useEffect(() => {
    lastPartUrl.current = lastPart?.url ?? null;
  });
  /** A start the automatic restart made, which is announced as one. */
  const automatic = useRef(false);
  const [restart] = useState(() => new AutoRestart());
  const restartState = useSyncExternalStore(
    restart.subscribe,
    restart.getSnapshot,
    restart.getSnapshot
  );

  const stepId = input.step_id;
  const snapshotOfContract = () => contractSnapshot(input, publishedFlowVersion);
  const partLabel = (index: number, durationMs: number) =>
    t("flow_transcript_rec_part_name", { part: index + 1, length: clockText(durationMs) });

  useEffect(() => {
    latestEntries.current = entries;
    recorder.setCallbacks({
      onPart: (part: RecordedPart) => {
        // Kept on the device while it uploads: a reload meanwhile still finds it.
        void keeper.keepPart(stepId, {
          sessionId: part.sessionId,
          index: part.index,
          blob: part.file,
          mimeType: part.file.type,
          durationMs: part.durationMs,
          capturedAt: part.capturedAt,
          contract: snapshotOfContract()
        });
        const label = partLabel(part.index, part.durationMs);
        const key = onPart(
          part.file,
          { sessionId: part.sessionId, index: part.index, durationMs: part.durationMs },
          label
        );
        liveEntry.current = key ?? null;
        // The part can be heard here at once, before its upload is done.
        setLastPart((previous) => {
          if (previous) URL.revokeObjectURL(previous.url);
          return key ? { key, url: URL.createObjectURL(part.file) } : null;
        });
      },
      journal: keeper.journalFor(stepId, snapshotOfContract),
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
      restart.cancel();
      recorder.dispose();
      live.discard();
      if (lastPartUrl.current) URL.revokeObjectURL(lastPartUrl.current);
    },
    [recorder, live, restart]
  );

  // Status changes are announced politely; the clock, the meter and the words are not.
  useEffect(() => {
    let phase = recorder.getSnapshot().phase;
    let status = live.getSnapshot().status;
    let hint: MicrophoneHint | null = null;
    let quietTold = false;
    const offRecorder = recorder.subscribe(() => {
      const next = recorder.getSnapshot();
      if (next.micHint !== hint) {
        hint = next.micHint;
        // Each hint once as it appears; "quiet" once per recording, as meetings have pauses.
        if (hint && (hint !== "silent" || !quietTold)) {
          quietTold ||= hint === "silent";
          announce(micHintText(hint, translate.current));
        }
      }
      if (next.phase === phase) return;
      const restarted = automatic.current && next.phase === "recording";
      if (next.phase === "recording" && phase !== "paused") quietTold = false;
      const message = restarted
        ? null
        : next.phase === "recording"
          ? phase === "paused"
            ? "flow_transcript_rec_resumed_announce"
            : "flow_transcript_rec_started_announce"
          : next.phase === "paused"
            ? "flow_transcript_rec_paused_announce"
            : next.phase === "stopping"
              ? "flow_transcript_rec_stopped_announce"
              : null;
      const lost =
        phase === "stopping" && next.phase === "idle" && next.ended && LOST.has(next.ended);
      phase = next.phase;
      if (next.phase !== "starting") automatic.current = false;
      if (message) announce(translate.current(message));
      if (lost) {
        announce(translate.current("flow_transcript_rec_restarting_announce"));
        restart.lost();
      }
    });
    const offRestart = restart.subscribe(() => {
      if (restart.getSnapshot().phase === "failed") {
        announce(translate.current("flow_transcript_rec_restart_failed_title"));
      }
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
      offRestart();
    };
  }, [recorder, live, restart, announce]);

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

  // What this device kept of earlier recordings of the step, offered to continue.
  const scan = useQuery({
    queryKey: ["flow-recordings", flowId, stepId, "kept"],
    queryFn: () => keeper.scan(stepId),
    enabled: keeper.available,
    staleTime: Infinity,
    gcTime: 0,
    retry: false
  });
  /** Kept recordings continued or discarded here, which are not offered again. */
  const [handled, setHandled] = useState<ReadonlySet<string>>(new Set());
  const [promptDismissed, setPromptDismissed] = useState(false);
  const [resumeBusy, setResumeBusy] = useState<"continue" | "discard" | null>(null);
  const [resumeProblem, setResumeProblem] = useState<string | null>(null);
  const onForm = new Set(entries.flatMap((entry) => entry.recording?.sessionId ?? []));
  const offered = (scan.data?.saved ?? []).find(
    (saved) => !onForm.has(saved.sessionId) && !handled.has(saved.sessionId)
  );

  function settle(saved: SavedRecording) {
    setHandled((current) => new Set(current).add(saved.sessionId));
    setResumeProblem(null);
  }

  async function continueSaved(saved: SavedRecording) {
    setResumeBusy("continue");
    setResumeProblem(null);
    try {
      let parts: StoredPart[];
      try {
        parts = await keeper.readSession(stepId, saved.sessionId);
      } catch {
        setResumeProblem(t("flow_transcript_resume_read_failed"));
        return;
      }
      if (parts.length === 0) {
        settle(saved);
        return;
      }
      // The flow may have changed since: its step must still take these parts as they are.
      const refusal = resumeRefusal(snapshotOfContract(), parts);
      if (refusal) {
        setResumeProblem(resumeRefusalText(refusal, t));
        return;
      }
      keeper.adopt(stepId, parts);
      setSession(saved.sessionId);
      for (const part of parts) {
        onPart(
          storedPartFile(part),
          { sessionId: part.sessionId, index: part.index, durationMs: part.durationMs },
          partLabel(part.index, part.durationMs)
        );
      }
      settle(saved);
      announce(t("flow_transcript_resume_added"));
    } finally {
      setResumeBusy(null);
    }
  }

  async function discardSaved(saved: SavedRecording) {
    setResumeBusy("discard");
    setResumeProblem(null);
    const discarded = await keeper.forgetSession(stepId, saved.sessionId);
    setResumeBusy(null);
    if (!discarded) {
      setResumeProblem(t("flow_transcript_resume_discard_failed"));
      return;
    }
    settle(saved);
    announce(t("flow_transcript_resume_discarded"));
  }

  // Where the form's recorded parts are kept, which "Spara och fortsätt senare" needs.
  useSyncExternalStore(keeper.subscribe, keeper.getVersion, keeper.getVersion);
  const recorded = entries.flatMap((entry) => (entry.recording ? [entry.recording] : []));
  const keeping = recorded.map((part) => keeper.keeping(stepId, part.sessionId, part.index));
  const laterBlocked =
    snapshot.phase !== "idle" || keeping.some((where) => where === undefined)
      ? t("flow_transcript_save_later_busy")
      : keeping.some((where) => where === "tab")
        ? t("flow_transcript_save_later_only_in_tab")
        : null;
  const degradation = keeper.available ? keeper.degradation(stepId) : "failed";

  const laterId = useId();
  const startButton = useRef<HTMLButtonElement>(null);
  const [discardProblem, setDiscardProblem] = useState(false);
  const [filesFull, setFilesFull] = useState(false);
  const [backlogFull, setBacklogFull] = useState(false);
  const limits = recordingLimits(input, options.audioBitsPerSecond);

  /**
   * Starts recording, continuing the recording whose parts are on the form;
   * null when the step refuses another part now (no file slot, parts
   * waiting for their upload, or, for an automatic start, no time left).
   */
  function start({ automatic: byItself = false } = {}): Promise<void> | null {
    if (recorder.getSnapshot().phase !== "idle") return null;
    if (!byItself) restart.cancel();
    const now = latestEntries.current;
    if (filesLeft(input, now) < 1) {
      setFilesFull(true);
      return null;
    }
    setFilesFull(false);
    if (awaitingUpload(now) >= MAX_PARTS_AWAITING_UPLOAD) {
      setBacklogFull(true);
      return null;
    }
    setBacklogFull(false);
    const current = session ?? latestSession(now);
    const before = partsOf(current, now);
    // Recording again while the last recording's parts are on the form goes on with it.
    const sessionId = before.length > 0 && current ? current : crypto.randomUUID();
    const firstIndex = before.reduce((next, part) => Math.max(next, part.index + 1), 0);
    const recordedBeforeMs = before.reduce((sum, part) => sum + part.durationMs, 0);
    if (
      byItself &&
      recordingTimeLeftMs(limits.maxRecordingMs, before.length + 1, recordedBeforeMs) <= 0
    ) {
      return null;
    }
    setSession(sessionId);
    automatic.current = byItself;
    return recorder.start({
      sessionId,
      firstIndex,
      limits: (): RecorderLimits => ({
        ...limits,
        recordedBeforeMs,
        partsBefore: before.length,
        filesLeft: filesLeft(input, latestEntries.current),
        awaitingUpload: awaitingUpload(latestEntries.current)
      })
    });
  }

  /**
   * Throws the step's whole recording away: its parts leave the form (their
   * uploads stop or are deleted) and nothing of it stays on the device. The
   * next recording starts a new one.
   */
  async function discardRecording() {
    const parts = latestEntries.current.filter((entry) => entry.recording);
    const sessions = new Set(parts.map((entry) => entry.recording!.sessionId));
    if (session) sessions.add(session);
    const forgotten = await Promise.all(
      [...sessions].map((sessionId) => keeper.forgetSession(stepId, sessionId))
    );
    restart.cancel();
    live.discard();
    recorder.dismiss();
    liveEntry.current = null;
    flushSync(() => {
      onDiscard?.(parts.map((entry) => entry.key));
      setSession(null);
      setHandled((current) => new Set([...current, ...sessions]));
      setLastPart((previous) => {
        if (previous) URL.revokeObjectURL(previous.url);
        return null;
      });
      setFilesFull(false);
      setBacklogFull(false);
      setDiscardProblem(forgotten.some((done) => !done));
    });
    // The button and its dialog are gone: recording again is what comes next.
    startButton.current?.focus();
    announce(t("flow_transcript_discard_done"));
  }

  useEffect(() => {
    restart.setHandlers({
      attempt: async (): Promise<RestartOutcome> => {
        const started = start({ automatic: true });
        if (!started) return "refused";
        await started;
        const { phase, problem } = recorder.getSnapshot();
        if (phase === "recording" || phase === "paused") return "started";
        // A microphone the person or the browser refused stays refused.
        return problem === "permission_denied" ? "refused" : "failed";
      },
      onStarted: () => announce(t("flow_transcript_rec_restarted_announce"))
    });
  });

  if (!recordsInto(input, options.mimeType)) {
    return (
      <Banner
        status="info"
        title={t("flow_transcript_rec_heading")}
        description={t("flow_transcript_rec_wrong_type")}
        collapsible={false}
      />
    );
  }

  if (support !== "supported") {
    return (
      <Banner
        status="info"
        title={t("flow_transcript_rec_heading")}
        description={problemText(support, t)}
        collapsible={false}
      />
    );
  }

  const { phase, problem, ended } = snapshot;
  const formParts = partsOf(session ?? latestSession(entries), entries);
  const continues = formParts.length > 0;
  const running = phase === "recording" || phase === "paused";
  // What recording more may still hold, said once a recording has parts on the form.
  const roomMs =
    continues && limits.maxRecordingMs
      ? recordingTimeLeftMs(
          limits.maxRecordingMs,
          formParts.length + 1,
          formParts.reduce((sum, part) => sum + part.durationMs, 0)
        )
      : null;

  /** What the step lets a recording hold, as the form says it under its heading. */
  function limitHint(): string | null {
    if (roomMs !== null) {
      return roomMs >= 60_000
        ? t("flow_transcript_rec_room_hint", {
            length: lengthText(Math.floor(roomMs / 60_000) * 60_000, t)
          })
        : null;
    }
    if (limits.maxRecordingMs) {
      return t("flow_transcript_rec_length_hint", { length: lengthText(limits.maxRecordingMs, t) });
    }
    // No length limit: how long one file of the most a file may be holds at this bit rate.
    const maxBytes = input.max_file_size_bytes;
    if (!maxBytes) return null;
    return t("flow_transcript_rec_file_hint", {
      size: formatBytes(maxBytes, locale),
      length: lengthText(((maxBytes * 8) / options.audioBitsPerSecond) * 1000, t)
    });
  }
  const hint = limitHint();

  return (
    <div className="border-ax-border rounded-ax-inner flex flex-col gap-3 border p-3">
      <div className="flex flex-col gap-1">
        <Heading level={4}>{t("flow_transcript_rec_heading")}</Heading>
        <Text type="supporting" as="p">
          {t("flow_transcript_rec_hint")}
          {hint ? ` ${hint}` : null}
        </Text>
      </div>

      {offered && !promptDismissed ? (
        <div className="flex flex-col gap-2">
          <ResumePrompt
            saved={offered}
            busy={resumeBusy}
            onContinue={() => void continueSaved(offered)}
            onDiscard={() => void discardSaved(offered)}
            onDismiss={() => {
              setPromptDismissed(true);
              setResumeProblem(null);
            }}
          />
          {resumeProblem ? (
            <Banner
              status="error"
              title={t("flow_transcript_resume_problem_title")}
              description={resumeProblem}
              collapsible={false}
            />
          ) : null}
        </div>
      ) : null}
      {scan.data?.incomplete || scan.isError ? (
        <Banner
          status="warning"
          title={t("flow_transcript_resume_scan_failed_title")}
          description={t("flow_transcript_resume_scan_failed")}
          collapsible={false}
          endContent={
            <Button
              label={t("flow_transcript_resume_scan_retry")}
              size="sm"
              isLoading={scan.isFetching}
              isInterruptible
              onClick={() => {
                if (!scan.isFetching) void scan.refetch();
              }}
            />
          }
        />
      ) : null}

      {problem ? (
        <Banner
          status="error"
          title={t("flow_transcript_rec_problem_title")}
          description={problemText(problem, t)}
          collapsible={false}
        />
      ) : null}
      {degradation === "failed" && (phase !== "idle" || recorded.length > 0) ? (
        <Banner
          status="warning"
          title={t("flow_transcript_storage_degraded_title")}
          description={t("flow_transcript_storage_degraded")}
          collapsible={false}
        />
      ) : degradation === "unavailable" && phase !== "idle" ? (
        <Banner
          status="info"
          title={t("flow_transcript_storage_on_part_end_title")}
          description={t("flow_transcript_storage_on_part_end")}
          collapsible={false}
        />
      ) : null}
      {discardProblem ? (
        <Banner
          status="warning"
          title={t("flow_transcript_discard_partly_title")}
          description={t("flow_transcript_discard_partly")}
          collapsible={false}
        />
      ) : null}
      {filesFull ? (
        <Banner
          status="warning"
          title={t("flow_transcript_rec_problem_title")}
          description={t("flow_transcript_rec_files_full", { count: input.max_files ?? 0 })}
          collapsible={false}
        />
      ) : null}
      {backlogFull ? (
        <Banner
          status="warning"
          title={t("flow_transcript_rec_problem_title")}
          description={t("flow_transcript_rec_backlog_full")}
          collapsible={false}
        />
      ) : null}
      {restartState.phase === "waiting" ? (
        <Banner
          status="warning"
          title={t("flow_transcript_rec_restarting_title")}
          description={restartingText(ended, t)}
          collapsible={false}
        />
      ) : restartState.phase === "failed" ? (
        <Banner
          status="error"
          title={t("flow_transcript_rec_restart_failed_title")}
          description={t("flow_transcript_rec_restart_failed")}
          collapsible={false}
        />
      ) : ended && ended !== "manual" && phase === "idle" ? (
        <Banner
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
            ref={startButton}
            label={continues ? t("flow_transcript_rec_continue") : t("flow_transcript_rec_start")}
            icon={<Mic aria-hidden="true" />}
            variant="primary"
            isLoading={phase === "starting"}
            isInterruptible
            onClick={() => void start()}
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

      {running ? (
        <RecordingSize
          bytes={snapshot.partBytes}
          maxBytes={input.max_file_size_bytes ?? null}
          bitsPerSecond={options.audioBitsPerSecond}
        />
      ) : null}

      {onSaveForLater && keeper.available && recorded.length > 0 ? (
        <div className="flex flex-col gap-1">
          <div>
            <Button
              label={t("flow_transcript_save_later")}
              size="sm"
              aria-describedby={laterId}
              onClick={() => {
                if (laterBlocked) announce(laterBlocked);
                else onSaveForLater();
              }}
            />
          </div>
          <Text type="supporting" as="p" id={laterId}>
            {laterBlocked ?? t("flow_transcript_save_later_hint")}
          </Text>
        </div>
      ) : null}

      {onDiscard && phase === "idle" && recorded.length > 0 ? (
        <DiscardRecording onDiscard={discardRecording} />
      ) : null}

      {running ? <LevelMeter recorder={recorder} hint={snapshot.micHint} /> : null}
      {phase === "idle" && lastPart && entries.some((entry) => entry.key === lastPart.key) ? (
        <LastPartPreview url={lastPart.url} />
      ) : null}

      <LiveText snapshot={text} />

      <RecordingDiagnostics
        report={() =>
          recordingReport({
            recorder,
            parts: partDiagnostics(latestEntries.current, (sessionId, index) =>
              keeper.keeping(stepId, sessionId, index)
            ),
            storage: degradation,
            live: liveAvailable ? live.getSnapshot().status : null
          })
        }
      />
    </div>
  );
}
