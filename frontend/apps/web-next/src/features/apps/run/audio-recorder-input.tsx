import { Download, Mic, Square, Trash2 } from "lucide-react";
import { useLocale, useTranslations } from "use-intl";
import { useEffect, useRef, useState } from "react";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Collapsible } from "@/components/astryx/collapsible";
import { Button } from "@astryxdesign/core/Button";
import { IconButton } from "@astryxdesign/core/IconButton";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { inputFieldRules } from "@/features/files/upload-plan";
import { saveBlob } from "@/features/files/signed-file-url";
import { formatBytes, formatDateTime } from "@/lib/format";
import { browserWakeLock, ScreenWakeLock } from "@/lib/audio/screen-wake-lock";
import { withRecordedDuration } from "@/lib/audio/webm-duration";
import { useBeforeUnloadWarning } from "@/lib/hooks/use-before-unload-warning";
import { toast } from "@/lib/toast";
import type { InputField } from "../apps";
import { FileChip } from "./upload-input";
import type { RunFile } from "./use-app-run";

const TIMESLICE_MS = 10_000;
const STALL_TIMEOUT_MS = 20_000;
const AUDIO_CONSTRAINTS: MediaTrackConstraints = {
  noiseSuppression: true,
  echoCancellation: true,
  autoGainControl: true
};

function microphoneErrorKey(error: unknown) {
  switch (error instanceof DOMException ? error.name : "") {
    case "NotAllowedError":
    case "PermissionDeniedError":
      return "recording_error_permission";
    case "NotFoundError":
      return "recording_error_not_found";
    case "NotReadableError":
      return "recording_error_not_readable";
    case "OverconstrainedError":
      return "recording_error_overconstrained";
    case "SecurityError":
      return "recording_error_security";
    case "NotSupportedError":
      return "recording_error_not_supported";
    default:
      return "recording_error_generic";
  }
}

function mediaErrorDetails(error: unknown): string {
  return error instanceof Error ? `${error.name}: ${error.message}` : String(error);
}

function pickMimeType(): string {
  if (typeof MediaRecorder === "undefined") return "audio/webm";
  return MediaRecorder.isTypeSupported("audio/mp4") ? "audio/mp4" : "audio/webm;codecs=opus";
}

type Capture = {
  phase: "acquiring" | "recording" | "stopping";
  stream: MediaStream | null;
  recorder: MediaRecorder | null;
  context: AudioContext | null;
  raf: number | null;
  cleanupListeners: () => void;
  stallTimer: ReturnType<typeof setInterval> | null;
  diagnostics: string[];
  /** A phone whose screen locks can stop the capture: the screen stays on while recording. */
  wakeLock: ScreenWakeLock;
};

function releaseCapture(capture: Capture) {
  capture.wakeLock.release();
  capture.cleanupListeners();
  if (capture.stallTimer !== null) clearInterval(capture.stallTimer);
  if (capture.raf !== null) cancelAnimationFrame(capture.raf);
  capture.stream?.getTracks().forEach((track) => track.stop());
  if (capture.recorder && capture.recorder.state !== "inactive") capture.recorder.stop();
  void capture.context?.close().catch(() => undefined);
}

function formatElapsed(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

/**
 * Microphone recorder for an `audio-recorder` app input. Condensed port of the
 * Svelte AudioRecorder: timesliced capture, size-limit auto-stop, a volume
 * meter, then a preview the user explicitly queues for the run.
 */
export function AudioRecorderInput({
  field,
  description,
  files,
  onAddFiles,
  onRemoveFile
}: {
  field: InputField;
  description?: string | null;
  files: RunFile[];
  onAddFiles: (files: File[], rules: ReturnType<typeof inputFieldRules>) => void;
  onRemoveFile: (key: string) => void;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const announce = useAnnounce();
  const rules = inputFieldRules(field);
  const maxBytes = Number.isFinite(rules.maxSize) ? rules.maxSize : null;

  const [phase, setPhase] = useState<"idle" | Capture["phase"]>("idle");
  const recording = phase === "recording";
  const busy = phase === "acquiring" || phase === "stopping";
  const [elapsed, setElapsed] = useState(0);
  const [volume, setVolume] = useState(0);
  const [bytes, setBytes] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [diagnostics, setDiagnostics] = useState<string | null>(null);
  const [recorded, setRecorded] = useState<{ file: File; url: string } | null>(null);
  const [discardOpen, setDiscardOpen] = useState(false);

  const captureRef = useRef<Capture | null>(null);
  const previewUrlRef = useRef<string | null>(null);

  useEffect(() => {
    const message = error || warning;
    if (message) announce(message);
  }, [error, warning, announce]);

  // A reload loses a recording until it is queued for the run and uploaded,
  // also while Stop is finalizing it.
  useBeforeUnloadWarning(
    recording ||
      phase === "stopping" ||
      (recorded !== null && files.length === 0) ||
      files.some((file) => file.uploading)
  );

  useEffect(
    () => () => {
      const capture = captureRef.current;
      captureRef.current = null;
      if (capture) releaseCapture(capture);
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    },
    []
  );

  async function startRecording() {
    if (captureRef.current) return;
    const capture: Capture = {
      phase: "acquiring",
      stream: null,
      recorder: null,
      context: null,
      raf: null,
      stallTimer: null,
      diagnostics: [],
      cleanupListeners: () => {},
      wakeLock: new ScreenWakeLock(browserWakeLock())
    };
    captureRef.current = capture;
    setPhase("acquiring");
    setError(null);
    setWarning(null);
    setDiagnostics(null);
    try {
      if (
        !navigator.mediaDevices?.getUserMedia ||
        typeof MediaRecorder === "undefined" ||
        typeof AudioContext === "undefined"
      ) {
        throw new DOMException("Microphone recording APIs are unavailable", "NotSupportedError");
      }
      let stream: MediaStream;
      let fallback = false;
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: AUDIO_CONSTRAINTS });
      } catch (primaryError) {
        if (captureRef.current !== capture) return;
        if (
          !(primaryError instanceof DOMException) ||
          !["NotFoundError", "OverconstrainedError"].includes(primaryError.name)
        )
          throw primaryError;
        capture.diagnostics.push(mediaErrorDetails(primaryError));
        fallback = true;
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      }
      if (captureRef.current !== capture) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      capture.stream = stream;
      const track = stream.getAudioTracks()[0];
      if (fallback && track?.applyConstraints) {
        try {
          await track.applyConstraints(AUDIO_CONSTRAINTS);
        } catch (constraintError) {
          capture.diagnostics.push(mediaErrorDetails(constraintError));
        }
        if (captureRef.current !== capture) return;
      }
      const context = new AudioContext();
      capture.context = context;
      const analyser = context.createAnalyser();
      context.createMediaStreamSource(stream).connect(analyser);
      const recorder = new MediaRecorder(stream, { mimeType: pickMimeType() });
      capture.recorder = recorder;
      const chunks: Blob[] = [];
      let totalBytes = 0;
      let lastChunkAt = Date.now();
      /** Monotonic time the recorder started, for the duration written into the file. */
      let recordingSince = 0;
      setBytes(0);
      const receiveData = (event: BlobEvent) => {
        if (captureRef.current !== capture || event.data.size === 0) return;
        lastChunkAt = Date.now();
        chunks.push(event.data);
        totalBytes += event.data.size;
        setBytes(totalBytes);
        if (maxBytes && totalBytes >= maxBytes && capture.phase === "recording") {
          setWarning(t("recording_limit_reached"));
          stopRecording();
        }
      };
      const finalize = async () => {
        if (captureRef.current !== capture) return;
        // Measured at the stop, before the header is read.
        const durationMs = Math.max(0, performance.now() - recordingSince);
        releaseCapture(capture);
        const mimeType = recorder.mimeType || pickMimeType();
        // The first chunk holds a WebM header without a duration; written in, a
        // player can tell the length and seek.
        const [first, ...rest] = chunks;
        let head = first;
        if (first) {
          try {
            head = await withRecordedDuration(first, durationMs, mimeType);
          } catch {
            // The header stays as recorded: players then guess the length.
          }
        }
        // Unmounted meanwhile: the capture was released and nothing is shown.
        if (captureRef.current !== capture) return;
        captureRef.current = null;
        const blob = new Blob(head ? [head, ...rest] : [], { type: mimeType });
        if (blob.size > 0) {
          // File validation uses MIME essence; codecs describe the recording transport.
          const fileType = mimeType.split(";")[0]!.trim();
          const extension = fileType.replace("audio/", "") || "webm";
          const now = new Date();
          const datetime =
            `${formatDateTime(now.toISOString())}-${String(now.getSeconds()).padStart(2, "0")}`.replaceAll(
              ":",
              "-"
            );
          const file = new File(
            [blob],
            `${t("recording_filename_template", { datetime })}.${extension}`,
            { type: fileType }
          );
          if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
          const url = URL.createObjectURL(blob);
          previewUrlRef.current = url;
          setRecorded({ file, url });
        } else {
          setWarning(null);
          setError(t("no_audio_data_captured"));
        }
        setPhase("idle");
        setVolume(0);
      };
      const disconnected = () => {
        if (captureRef.current !== capture || capture.phase !== "recording") return;
        setWarning(t("app_recording_device_disconnected"));
        stopRecording();
      };
      const failed = (event: Event) => {
        if (captureRef.current !== capture || capture.phase !== "recording") return;
        setWarning(t("recording_saved_after_error"));
        capture.diagnostics.push(
          mediaErrorDetails((event as ErrorEvent).error ?? "MediaRecorder error")
        );
        setDiagnostics(
          [
            ...capture.diagnostics,
            `chunks=${chunks.length} bytes=${totalBytes} mimeType=${recorder.mimeType}`
          ].join("\n")
        );
        stopRecording();
      };
      stream.addEventListener("inactive", disconnected);
      const tracks = stream.getAudioTracks();
      tracks.forEach((track) => track.addEventListener("ended", disconnected));
      recorder.addEventListener("error", failed);
      recorder.addEventListener("dataavailable", receiveData);
      const stopped = () => void finalize();
      recorder.addEventListener("stop", stopped);
      capture.cleanupListeners = () => {
        stream.removeEventListener("inactive", disconnected);
        tracks.forEach((track) => track.removeEventListener("ended", disconnected));
        recorder.removeEventListener("error", failed);
        recorder.removeEventListener("dataavailable", receiveData);
        recorder.removeEventListener("stop", stopped);
      };
      recorder.start(TIMESLICE_MS);
      recordingSince = performance.now();
      capture.phase = "recording";
      capture.wakeLock.hold();
      capture.stallTimer = setInterval(() => {
        if (captureRef.current !== capture || capture.phase !== "recording") return;
        if (Date.now() - lastChunkAt >= STALL_TIMEOUT_MS) {
          setWarning(t("recording_stalled"));
          stopRecording();
        }
      }, 1000);
      const startedAt = Date.now();
      const buffer = new Float32Array(analyser.fftSize);
      const tick = () => {
        if (captureRef.current !== capture || capture.phase !== "recording") return;
        analyser.getFloatTimeDomainData(buffer);
        let sum = 0;
        for (const amplitude of buffer) sum += amplitude * amplitude;
        setVolume(Math.min(1, Math.sqrt(sum / buffer.length) / 0.15));
        setElapsed((Date.now() - startedAt) / 1000);
        capture.raf = requestAnimationFrame(tick);
      };
      setElapsed(0);
      setPhase("recording");
      capture.raf = requestAnimationFrame(tick);
    } catch (caught) {
      if (captureRef.current !== capture) return;
      captureRef.current = null;
      releaseCapture(capture);
      setPhase("idle");
      setError(t(microphoneErrorKey(caught)));
      setDiagnostics(
        [
          ...capture.diagnostics,
          mediaErrorDetails(caught),
          `secureContext=${window.isSecureContext} protocol=${window.location.protocol} getUserMedia=${typeof navigator.mediaDevices?.getUserMedia} MediaRecorder=${typeof MediaRecorder}`
        ].join("\n")
      );
    }
  }

  function stopRecording() {
    const capture = captureRef.current;
    if (!capture?.recorder || capture.phase !== "recording") return;
    capture.phase = "stopping";
    setPhase("stopping");
    // An error may inactivate the recorder before its final data/stop events.
    if (capture.recorder.state !== "inactive") capture.recorder.stop();
  }

  function discardRecording() {
    setDiscardOpen(false);
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    previewUrlRef.current = null;
    setRecorded(null);
    setBytes(0);
    setError(null);
    setWarning(null);
    setDiagnostics(null);
  }

  return (
    <div className="flex w-full max-w-[60ch] flex-col items-center gap-3">
      {description && <span className="text-muted-foreground text-sm">{description}</span>}

      {files.length > 0 && (
        <div className="flex w-full min-w-0 flex-col gap-2">
          {files.map((file) => (
            <FileChip key={file.key} file={file} onRemove={() => onRemoveFile(file.key)} />
          ))}
        </div>
      )}
      {recorded ? (
        <>
          <audio controls src={recorded.url} className="w-full" />
          <div className="flex flex-wrap items-center justify-center gap-2">
            {files.length === 0 && (
              <Button
                variant="primary"
                label={t("use_this_recording")}
                onClick={() => onAddFiles([recorded.file], rules)}
              />
            )}
            <Button
              label={t("save_as_file")}
              icon={<Download className="size-4" />}
              onClick={() => {
                try {
                  saveBlob(recorded.file, recorded.file.name);
                } catch {
                  toast.error(t("recording_save_failed"));
                }
              }}
            />
            <Button
              variant="ghost"
              label={t("discard")}
              icon={<Trash2 className="size-4" />}
              onClick={() => setDiscardOpen(true)}
            />
          </div>
        </>
      ) : files.length === 0 ? (
        <div className="border-border bg-background flex items-center gap-3 rounded-full border p-2 shadow-sm">
          <IconButton
            type="button"
            variant={recording ? "destructive" : "primary"}
            className="size-12 rounded-full"
            label={recording ? t("stop_recording") : t("start_recording")}
            tooltip={recording ? t("stop_recording") : t("start_recording")}
            isLoading={busy}
            isInterruptible
            onClick={recording ? stopRecording : startRecording}
            icon={recording ? <Square className="size-5" /> : <Mic className="size-5" />}
          />
          {recording ? (
            <div className="flex flex-col gap-1 pr-3 font-mono">
              <div className="flex items-center gap-3">
                <span className="tabular-nums">{formatElapsed(elapsed)}</span>
                <span className="bg-muted h-2 w-16 overflow-hidden rounded-full">
                  <span
                    className="bg-primary block h-full origin-left rounded-full"
                    style={{ transform: `scaleX(${volume})` }}
                  />
                </span>
              </div>
              {maxBytes && (
                <span className="text-muted-foreground text-xs">
                  {formatBytes(bytes, locale)} / {formatBytes(maxBytes, locale)}
                </span>
              )}
            </div>
          ) : (
            <span className="text-muted-foreground pr-4 text-sm">{t("start_recording")}</span>
          )}
        </div>
      ) : null}

      {error && <span className="text-destructive text-sm">{error}</span>}
      {warning && <p className="text-muted-foreground text-sm">{warning}</p>}
      {diagnostics && (
        <div className="w-full min-w-0">
          <Collapsible trigger={t("view_diagnostics")} defaultIsOpen={false}>
            <pre className="text-xs break-words whitespace-pre-wrap">{diagnostics}</pre>
          </Collapsible>
        </div>
      )}
      <ConfirmDialogControlled
        open={discardOpen}
        onOpenChange={setDiscardOpen}
        title={t("discard")}
        description={t("confirm_discard_recording")}
        confirmLabel={t("discard")}
        onConfirm={discardRecording}
      />
    </div>
  );
}
