"use client";

import { Mic, Square, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { inputFieldRules } from "@/features/files/upload-plan";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { InputField } from "../apps";
import { FileChip } from "./upload-input";
import type { RunFile } from "./use-app-run";

const TIMESLICE_MS = 10_000;

function pickMimeType(): string {
  if (typeof MediaRecorder === "undefined") return "audio/webm";
  return MediaRecorder.isTypeSupported("audio/mp4;codecs=avc1")
    ? "audio/mp4;codecs=avc1"
    : "audio/webm;codecs=opus";
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
  const rules = inputFieldRules(field);
  const maxBytes = Number.isFinite(rules.maxSize) ? rules.maxSize : null;

  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [volume, setVolume] = useState(0);
  const [bytes, setBytes] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [recorded, setRecorded] = useState<{ file: File; url: string } | null>(null);

  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const totalBytesRef = useRef(0);
  const startedAtRef = useRef(0);
  const rafRef = useRef<number | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const previewUrlRef = useRef<string | null>(null);

  // Release media + animation handles on unmount (and the preview blob URL,
  // tracked via a ref so the latest value is freed, not the mount-time null).
  useEffect(() => {
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      if (recorderRef.current && recorderRef.current.state !== "inactive") {
        recorderRef.current.stop();
      }
      streamRef.current?.getTracks().forEach((track) => track.stop());
      void audioContextRef.current?.close().catch(() => undefined);
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    };
  }, []);

  const tick = () => {
    const analyser = analyserRef.current;
    if (analyser) {
      const buffer = new Float32Array(analyser.fftSize);
      analyser.getFloatTimeDomainData(buffer);
      let sum = 0;
      for (const amplitude of buffer) sum += amplitude * amplitude;
      setVolume(Math.min(1, Math.sqrt(sum / buffer.length) / 0.15));
    }
    setElapsed((Date.now() - startedAtRef.current) / 1000);
    rafRef.current = requestAnimationFrame(tick);
  };

  async function startRecording() {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { noiseSuppression: true, echoCancellation: true, autoGainControl: true }
      });
      streamRef.current = stream;

      const audioContext = new AudioContext();
      const analyser = audioContext.createAnalyser();
      audioContext.createMediaStreamSource(stream).connect(analyser);
      audioContextRef.current = audioContext;
      analyserRef.current = analyser;

      const mimeType = pickMimeType();
      const recorder = new MediaRecorder(stream, { mimeType });
      recorderRef.current = recorder;
      chunksRef.current = [];
      totalBytesRef.current = 0;
      setBytes(0);

      recorder.addEventListener("dataavailable", (event) => {
        if (event.data.size === 0) return;
        chunksRef.current.push(event.data);
        totalBytesRef.current += event.data.size;
        setBytes(totalBytesRef.current);
        if (maxBytes && totalBytesRef.current >= maxBytes) {
          toast.warning(t("recording_limit_reached"));
          stopRecording();
        }
      });

      recorder.addEventListener("stop", () => {
        const blob = new Blob(chunksRef.current, { type: mimeType });
        if (blob.size > 0) {
          const extension = mimeType.replace("audio/", "").split(";")[0] || "webm";
          const file = new File([blob], `recording.${extension}`, { type: mimeType });
          const url = URL.createObjectURL(blob);
          previewUrlRef.current = url;
          setRecorded({ file, url });
        }
        streamRef.current?.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
        void audioContextRef.current?.close().catch(() => undefined);
        audioContextRef.current = null;
        analyserRef.current = null;
        setVolume(0);
      });

      recorder.start(TIMESLICE_MS);
      startedAtRef.current = Date.now();
      setElapsed(0);
      setRecording(true);
      rafRef.current = requestAnimationFrame(tick);
    } catch (caught) {
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
    setRecording(false);
    if (recorderRef.current && recorderRef.current.state !== "inactive") {
      recorderRef.current.stop();
    }
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
                  {formatBytes(bytes)} / {formatBytes(maxBytes)}
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
