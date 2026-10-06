"use client";

import { Mic, Square, Trash2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { inputFieldRules } from "@/features/files/upload-plan";
import { formatBytes } from "@/lib/format";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import type { InputField } from "../apps";
import { FileChip } from "./upload-input";
import type { RunFile } from "./use-app-run";

const TIMESLICE_MS = 10_000;

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
};

function releaseCapture(capture: Capture) {
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
  const rules = inputFieldRules(field);
  const maxBytes = Number.isFinite(rules.maxSize) ? rules.maxSize : null;

  const [phase, setPhase] = useState<"idle" | Capture["phase"]>("idle");
  const recording = phase === "recording";
  const busy = phase === "acquiring" || phase === "stopping";
  const [elapsed, setElapsed] = useState(0);
  const [volume, setVolume] = useState(0);
  const [bytes, setBytes] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [recorded, setRecorded] = useState<{ file: File; url: string } | null>(null);

  const captureRef = useRef<Capture | null>(null);
  const previewUrlRef = useRef<string | null>(null);

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
      raf: null
    };
    captureRef.current = capture;
    setPhase("acquiring");
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { noiseSuppression: true, echoCancellation: true, autoGainControl: true }
      });
      if (captureRef.current !== capture) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      capture.stream = stream;
      const context = new AudioContext();
      capture.context = context;
      const analyser = context.createAnalyser();
      context.createMediaStreamSource(stream).connect(analyser);
      const recorder = new MediaRecorder(stream, { mimeType: pickMimeType() });
      capture.recorder = recorder;
      const chunks: Blob[] = [];
      let totalBytes = 0;
      setBytes(0);
      recorder.addEventListener("dataavailable", (event) => {
        if (captureRef.current !== capture || event.data.size === 0) return;
        chunks.push(event.data);
        totalBytes += event.data.size;
        setBytes(totalBytes);
        if (maxBytes && totalBytes >= maxBytes && capture.phase === "recording") {
          toast.warning(t("recording_limit_reached"));
          stopRecording();
        }
      });
      recorder.addEventListener("stop", () => {
        if (captureRef.current !== capture) return;
        captureRef.current = null;
        releaseCapture(capture);
        const mimeType = recorder.mimeType || pickMimeType();
        const blob = new Blob(chunks, { type: mimeType });
        if (blob.size > 0) {
          // File validation uses MIME essence; codecs describe the recording transport.
          const fileType = mimeType.split(";")[0]!.trim();
          const extension = fileType.replace("audio/", "") || "webm";
          const file = new File([blob], `recording.${extension}`, { type: fileType });
          if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
          const url = URL.createObjectURL(blob);
          previewUrlRef.current = url;
          setRecorded({ file, url });
        }
        setPhase("idle");
        setVolume(0);
      });
      recorder.start(TIMESLICE_MS);
      capture.phase = "recording";
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
      const name = caught instanceof DOMException ? caught.name : "";
      setError(
        name === "NotAllowedError" || name === "PermissionDeniedError"
          ? t("recording_error_permission")
          : name === "NotFoundError"
            ? t("recording_error_not_found")
            : t("recording_error_generic")
      );
    }
  }

  function stopRecording() {
    const capture = captureRef.current;
    if (!capture?.recorder || capture.phase !== "recording") return;
    capture.phase = "stopping";
    setPhase("stopping");
    capture.recorder.stop();
  }

  function discardRecording() {
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    previewUrlRef.current = null;
    setRecorded(null);
    setBytes(0);
  }

  // Once queued into the run, show it like any other uploaded file.
  if (files.length > 0) {
    return (
      <div className="flex w-full max-w-[60ch] flex-col gap-2">
        {files.map((file) => (
          <FileChip key={file.key} file={file} onRemove={() => onRemoveFile(file.key)} />
        ))}
      </div>
    );
  }

  return (
    <div className="flex w-full max-w-[60ch] flex-col items-center gap-3">
      {description && <span className="text-muted-foreground text-sm">{description}</span>}

      {recorded ? (
        <>
          <audio controls src={recorded.url} className="w-full" />
          <div className="flex items-center gap-2">
            <Button onClick={() => onAddFiles([recorded.file], rules)}>
              {t("use_this_recording")}
            </Button>
            <Button variant="ghost" onClick={discardRecording}>
              <Trash2 className="size-4" /> {t("discard")}
            </Button>
          </div>
        </>
      ) : (
        <div className="border-border bg-background flex items-center gap-3 rounded-full border p-2 shadow-sm">
          <Button
            type="button"
            size="icon"
            variant={recording ? "destructive" : "default"}
            className="size-12 rounded-full"
            aria-label={recording ? t("stop_recording") : t("start_recording")}
            aria-busy={busy || undefined}
            onClick={recording ? stopRecording : startRecording}
          >
            {recording ? <Square className="size-5" /> : <Mic className="size-5" />}
          </Button>
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
      )}

      {error && <span className={cn("text-destructive text-sm")}>{error}</span>}
    </div>
  );
}
