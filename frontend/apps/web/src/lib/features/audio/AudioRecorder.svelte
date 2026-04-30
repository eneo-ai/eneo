<script lang="ts">
  import { IconMicrophone } from "@intric/icons/microphone";
  import { IconStop } from "@intric/icons/stop";
  import { IconDownload } from "@intric/icons/download";
  import { IconPlay } from "@intric/icons/play";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { onDestroy, onMount } from "svelte";

  import dayjs from "dayjs";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import {
    SPEECH_OPUS_BITRATE,
    estimateRecordingBytes,
    estimateRecordingDurationSeconds,
    selectAudioRecordingOptions
  } from "./audioRecordingOptions";
  import { buildRecordedAudioFile } from "./recordedAudioFile";
  import type { RecordingStopReason } from "./recordedAudioFile";
  import { downloadRecordedAudioFile } from "./downloadRecordedAudioFile";

  export let onRecordingDone: (params: {
    blob: Blob;
    mimeType: string;
    reason: RecordingStopReason;
    // Captured at finalize-time from the rAF tick clock; useful so callers
    // can label resumed segments by length without having to read the blob.
    durationMs: number;
  }) => void;
  // The session needs to know whether `true` came from a user click or from
  // its own retry path. Without this, the dialog had to infer intent by
  // peeking at session phase + a side-channel flag, which raced with the
  // queued retry timer. `meta.origin` makes intent explicit at the source.
  export let onRecordingStateChange: (
    isRecording: boolean,
    meta?: { origin: "user" | "external" }
  ) => void = () => {};

  type RecordingStartOrigin = "user" | "external";
  export let maxBytes: number | null = null;
  export let resetToken: unknown = 0;

  let isRecording: boolean = false;
  let startedRecordingAt = dayjs();
  let elapsedTime = "";
  let recordingError: string | null = null;
  let recordingErrorHint: string | null = null;
  let elapsedSeconds = 0;
  let recordingState: "idle" | "preparing" | "recording" | "processing" | "error" | "complete" =
    "idle";

  let volumeLevel: number = 0;

  let mediaStream: MediaStream | null;
  let mediaStreamNode: MediaStreamAudioSourceNode | null;
  let mediaRecorder: MediaRecorder | null;
  let audioContext: AudioContext | null;
  let analyserNode: AnalyserNode | null;
  let levelBuffer = new Float32Array();

  let recordingBuffer: Blob[] = [];
  let recordedBlob: Blob | null = null;
  let recordedMimeType = "";
  let completedRecordingAt = dayjs();
  let audioURL: string | null = null;
  let previewAudioEl: HTMLAudioElement | null = null;
  let isPreviewPlaying = false;
  let stopReason: RecordingStopReason = "manual";
  let handleStreamEnded: ((event: Event) => void) | null = null;
  let animationFrameId: number | null = null;
  let discardRecordingOnStop = false;
  let isDestroyed = false;
  let lastResetToken: unknown = resetToken;
  let activeAudioBitsPerSecond = SPEECH_OPUS_BITRATE;
  let lastMeterUpdateAt = 0;
  let lastAudibleAt = 0;
  let showMicSilentHint = false;
  let firstChunkSeen = false;
  let hiddenSinceMs: number | null = null;
  let stallIntervalId: ReturnType<typeof setInterval> | null = null;
  let requestDataPendingAt: number | null = null;
  let stopReasonLocked = false;
  let visibilityHandler: (() => void) | null = null;
  // Drives the inline "muted" / "reconnecting" hint below the volume meter.
  // We surface these as live status so the user knows the recorder is still
  // trying — silent failures are exactly what the previous version did.
  let isMicMuted = false;

  const TIMESLICE_MS = 2000;
  // Two-phase stall detection. On slower devices the encoder can take up to
  // ~10 s to emit the first chunk; once data is flowing a 5 s gap means the
  // capture has actually stopped (tab freeze, device disconnect, OS denial).
  // When the watchdog suspects a stall it first calls requestData() and
  // waits 2 s — this catches Firefox queuing delays under load before we
  // kill an otherwise-healthy session.
  const STALL_PRE_FIRST_CHUNK_MS = 10_000;
  const STALL_STEADY_STATE_MS = 5_000;
  const STALL_REQUEST_DATA_GRACE_MS = 2_000;
  const STALL_CHECK_INTERVAL_MS = 500;
  const METER_UPDATE_MS = 50;
  const MIC_ACTIVITY_THRESHOLD = 0.035;
  const MIC_SILENCE_HINT_MS = 6000;

  const formatMegabytes = (bytes: number) => (bytes / (1024 * 1024)).toFixed(2);
  let maxSizeLabel: string | null = null;
  $: maxSizeLabel =
    typeof maxBytes === "number" && Number.isFinite(maxBytes) && maxBytes > 0
      ? formatMegabytes(maxBytes)
      : null;

  let recordingStats = {
    chunks: 0,
    totalBytes: 0,
    lastChunkTime: 0,
    firstChunkSeenAt: 0,
    recorderMimeType: "",
    errors: [] as string[],
    requestDataAttempts: [] as { at: number; outcome: string }[],
    visibilityTransitions: [] as { at: number; state: string }[]
  };

  function setStopReason(reason: RecordingStopReason) {
    // Lock to the first non-default reason so a teardown sequence (e.g. a
    // limit hit followed by a stall during cleanup) cannot relabel the
    // original cause that the caller wants to surface.
    if (stopReasonLocked) return;
    stopReason = reason;
    stopReasonLocked = true;
  }

  function resetStopReason() {
    stopReason = "manual";
    stopReasonLocked = false;
  }

  let isLiveSizeEstimated = false;
  $: isLiveSizeEstimated =
    isRecording && recordingStats.chunks === 0 && elapsedSeconds > TIMESLICE_MS / 1000;

  let visibleRecordingBytes = 0;
  $: visibleRecordingBytes = isLiveSizeEstimated
    ? estimateRecordingBytes(elapsedSeconds, activeAudioBitsPerSecond)
    : recordingStats.totalBytes;

  let estimatedLimitLabel: string | null = null;
  $: estimatedLimitLabel =
    typeof maxBytes === "number" && Number.isFinite(maxBytes) && maxBytes > 0
      ? formatDurationEstimate(estimateRecordingDurationSeconds(maxBytes, activeAudioBitsPerSecond))
      : null;

  let estimatedRemainingLabel: string | null = null;
  $: estimatedRemainingLabel =
    typeof maxBytes === "number" && Number.isFinite(maxBytes) && maxBytes > 0
      ? formatDurationEstimate(
          estimateRecordingDurationSeconds(
            Math.max(maxBytes - visibleRecordingBytes, 0),
            activeAudioBitsPerSecond
          )
        )
      : null;

  let recordingRateLabel = "";
  $: recordingRateLabel = formatMegabytes(estimateRecordingBytes(3600, activeAudioBitsPerSecond));

  // The visible hint that explains *why* the meter is silent. Mute beats
  // reconnecting because a known-muted track is the more specific signal,
  // and reconnecting beats the existing silent-hint because the meter is
  // about to come back from the watchdog rescue.
  let micRecoveryHintKey: "muted" | "reconnecting" | null = null;
  $: micRecoveryHintKey = !isRecording
    ? null
    : isMicMuted
      ? "muted"
      : requestDataPendingAt !== null
        ? "reconnecting"
        : null;

  const audioConstraints: MediaTrackConstraints = {
    channelCount: 1,
    noiseSuppression: true,
    echoCancellation: true,
    autoGainControl: true
  };

  const isFallbackCandidate = (error: unknown) =>
    error instanceof DOMException &&
    (error.name === "NotFoundError" || error.name === "OverconstrainedError");

  const formatMediaError = (error: unknown) => {
    if (error instanceof DOMException) {
      return `${error.name}: ${error.message}`;
    }
    if (error instanceof Error) {
      return error.message;
    }
    return String(error);
  };

  const getFriendlyErrorMessage = (errorName: string | null) => {
    switch (errorName) {
      case "NotAllowedError":
      case "PermissionDeniedError":
        return m.recording_error_permission();
      case "NotFoundError":
        return m.recording_error_not_found();
      case "NotReadableError":
        return m.recording_error_not_readable();
      case "OverconstrainedError":
        return m.recording_error_overconstrained();
      case "SecurityError":
        return m.recording_error_security();
      case "NotSupportedError":
        return m.recording_error_not_supported();
      default:
        return m.recording_error_generic();
    }
  };

  const setRecordingErrorState = (message: string, error?: unknown) => {
    recordingError = error ? formatMediaError(error) : message;

    if (error instanceof DOMException) {
      recordingErrorHint = getFriendlyErrorMessage(error.name);
    } else if (message.includes("MediaDevices API is not available")) {
      recordingErrorHint = m.recording_error_not_supported();
    } else {
      recordingErrorHint = m.recording_error_generic();
    }
  };

  const collectMediaDiagnostics = async (context: string, error?: unknown) => {
    try {
      const hasMediaDevices = !!navigator.mediaDevices;
      const supportsGetUserMedia = !!navigator.mediaDevices?.getUserMedia;
      const supportsEnumerateDevices = !!navigator.mediaDevices?.enumerateDevices;
      const secureContext = window.isSecureContext;
      const protocol = window.location?.protocol ?? "unknown";

      recordingStats.errors.push(
        `${context} | secureContext=${secureContext} protocol=${protocol} mediaDevices=${supportsGetUserMedia}`
      );

      if (hasMediaDevices && supportsEnumerateDevices) {
        const devices = await navigator.mediaDevices.enumerateDevices();
        const audioInputs = devices.filter((device) => device.kind === "audioinput");
        const labeledInputs = audioInputs.filter((device) => device.label?.trim().length);
        recordingStats.errors.push(
          `Audio inputs detected: ${audioInputs.length} (${labeledInputs.length} labeled)`
        );
        console.warn("AudioRecorder diagnostics", {
          context,
          error,
          secureContext,
          protocol,
          devices
        });
      }
    } catch (diagnosticsError) {
      console.warn("AudioRecorder diagnostics failed", diagnosticsError);
    }
  };

  const requestAudioStream = async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      const errorMsg = "MediaDevices API is not available";
      recordingStats.errors.push(errorMsg);
      throw new Error(errorMsg);
    }

    try {
      return await navigator.mediaDevices.getUserMedia({
        audio: audioConstraints
      });
    } catch (error) {
      await collectMediaDiagnostics("Primary getUserMedia failed", error);
      if (!isFallbackCandidate(error)) {
        throw error;
      }

      recordingStats.errors.push("Retrying getUserMedia with relaxed audio constraints");

      try {
        const fallbackStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const track = fallbackStream.getAudioTracks()[0];
        if (track?.applyConstraints) {
          try {
            await track.applyConstraints(audioConstraints);
          } catch (applyError) {
            const applyErrorMsg = `Failed to apply audio constraints: ${formatMediaError(applyError)}`;
            recordingStats.errors.push(applyErrorMsg);
            console.warn(applyErrorMsg, applyError);
          }
        }
        return fallbackStream;
      } catch (fallbackError) {
        await collectMediaDiagnostics("Fallback getUserMedia failed", fallbackError);
        throw fallbackError;
      }
    }
  };

  function clearAudioPreviewUrl() {
    previewAudioEl?.pause();
    isPreviewPlaying = false;
    if (audioURL) {
      URL.revokeObjectURL(audioURL);
      audioURL = null;
    }
  }

  function clearCompletedRecording() {
    clearAudioPreviewUrl();
    recordedBlob = null;
    recordedMimeType = "";
    recordingBuffer = [];
    recordingError = null;
    recordingErrorHint = null;
    recordingStats = {
      chunks: 0,
      totalBytes: 0,
      lastChunkTime: 0,
      firstChunkSeenAt: 0,
      recorderMimeType: "",
      errors: [],
      requestDataAttempts: [],
      visibilityTransitions: []
    };
    firstChunkSeen = false;
    requestDataPendingAt = null;
    hiddenSinceMs = null;
    isMicMuted = false;
    elapsedSeconds = 0;
    elapsedTime = "";
    if (!isRecording && recordingState !== "preparing" && recordingState !== "processing") {
      recordingState = "idle";
    }
  }

  function stopMonitoringLoop() {
    if (animationFrameId !== null) {
      window.cancelAnimationFrame(animationFrameId);
      animationFrameId = null;
    }
  }

  function detachStreamEndedHandler() {
    if (mediaStream && handleStreamEnded) {
      const streamEndedHandler = handleStreamEnded;
      mediaStream.removeEventListener("inactive", streamEndedHandler);
      mediaStream.getAudioTracks().forEach((track) => {
        track.removeEventListener("ended", streamEndedHandler);
      });
    }
    handleStreamEnded = null;
  }

  function releaseMediaCapture() {
    stopMonitoringLoop();
    stopStallChecker();
    detachVisibilityHandler();
    mediaRecorder = null;
    mediaStreamNode?.disconnect();
    mediaStreamNode = null;
    analyserNode = null;
    levelBuffer = new Float32Array();
    volumeLevel = 0;
    showMicSilentHint = false;

    detachStreamEndedHandler();
    mediaStream?.getAudioTracks().forEach((track) => {
      track.stop();
    });
    mediaStream = null;

    const context = audioContext;
    audioContext = null;
    if (context && context.state !== "closed") {
      void context.close().catch((error) => {
        console.warn("Failed to close audio context", error);
      });
    }
  }

  function isMediaStreamLive(stream: MediaStream | null | undefined) {
    return !!stream?.active && stream.getAudioTracks().some((track) => track.readyState === "live");
  }

  async function prepareMediaCapture() {
    if (isMediaStreamLive(mediaStream) && analyserNode && audioContext) {
      return mediaStream;
    }

    releaseMediaCapture();
    const nextStream = await requestAudioStream();
    if (isDestroyed) {
      nextStream.getAudioTracks().forEach((track) => track.stop());
      throw new Error("Recorder was closed before microphone access completed.");
    }

    const streamEndedHandler = (_: Event) => {
      if (!isRecording) return;
      const errorMsg = m.recording_device_disconnected();
      setRecordingErrorState(errorMsg);
      recordingStats.errors.push(errorMsg + " at " + new Date().toISOString());
      setStopReason("error");
      stopRecording();
    };

    mediaStream = nextStream;
    handleStreamEnded = streamEndedHandler;
    mediaStream.addEventListener("inactive", streamEndedHandler);
    mediaStream.getAudioTracks().forEach((track) => {
      track.addEventListener("ended", streamEndedHandler);
      // mute/unmute fire on iOS during Bluetooth route changes and on some
      // platforms when the OS reclaims the mic briefly. Logging them helps
      // us debug intermittent reports, but we deliberately do not stop
      // recording here — the encoder keeps running and resumes producing
      // chunks once the route stabilises.
      track.addEventListener("mute", () => {
        isMicMuted = true;
        recordingStats.errors.push("Track muted at " + new Date().toISOString());
      });
      track.addEventListener("unmute", () => {
        isMicMuted = false;
        recordingStats.errors.push("Track unmuted at " + new Date().toISOString());
      });
    });

    audioContext = new AudioContext();
    analyserNode = audioContext.createAnalyser();
    levelBuffer = new Float32Array(analyserNode.fftSize);
    mediaStreamNode = audioContext.createMediaStreamSource(mediaStream);
    mediaStreamNode.connect(analyserNode);
    if (audioContext.state === "suspended") {
      await audioContext.resume();
    }

    return mediaStream;
  }

  // The session controller can call startExternal in parallel with a user
  // click on the record button (e.g. user manually presses record while a
  // queued retry timer is firing). Without this guard, the second call would
  // wipe `recordingBuffer` and tear down the in-flight MediaRecorder mid-
  // capture. Coalescing on `startPromise` makes startRecording reentrant-safe.
  let startPromise: Promise<void> | null = null;

  async function startRecording(origin: RecordingStartOrigin = "user"): Promise<void> {
    if (isRecording || recordingState === "recording" || recordingState === "preparing") {
      return startPromise ?? Promise.resolve();
    }
    if (startPromise) return startPromise;

    startPromise = doStartRecording(origin).finally(() => {
      startPromise = null;
    });
    return startPromise;
  }

  async function doStartRecording(origin: RecordingStartOrigin): Promise<void> {
    try {
      recordingBuffer = [];
      recordedBlob = null;
      recordedMimeType = "";
      recordingError = null;
      recordingErrorHint = null;
      recordingState = "preparing";
      resetStopReason();
      discardRecordingOnStop = false;
      clearAudioPreviewUrl();

      recordingStats = {
        chunks: 0,
        totalBytes: 0,
        // lastChunkTime is set after recorder.start() once the encoder is
        // actually running — initialising it here would charge the watchdog
        // for the time spent awaiting getUserMedia.
        lastChunkTime: 0,
        firstChunkSeenAt: 0,
        recorderMimeType: "",
        errors: [],
        requestDataAttempts: [],
        visibilityTransitions: []
      };
      firstChunkSeen = false;
      requestDataPendingAt = null;
      hiddenSinceMs = null;

      if (typeof MediaRecorder === "undefined") {
        throw new DOMException("MediaRecorder API is not available", "NotSupportedError");
      }

      const stream = await prepareMediaCapture();
      if (isDestroyed) {
        releaseMediaCapture();
        return;
      }

      if (stream) {
        const recordingOptions = selectAudioRecordingOptions();
        activeAudioBitsPerSecond = recordingOptions.audioBitsPerSecond;
        const recorder = new MediaRecorder(stream, recordingOptions);
        mediaRecorder = recorder;
        const initialMimeType = recorder.mimeType || recordingOptions.mimeType || "";

        recorder.addEventListener("dataavailable", (event) => {
          if (event.data.size > 0) {
            const now = performance.now();
            const maxBytesValue =
              typeof maxBytes === "number" && Number.isFinite(maxBytes) && maxBytes > 0
                ? maxBytes
                : null;
            const nextTotalBytes = recordingStats.totalBytes + event.data.size;

            // Always retain the chunk before the size-limit stop. Dropping
            // it would discard up to TIMESLICE_MS of audio that the user
            // already produced; a few hundred bytes over the cap is the
            // less-bad outcome.
            recordingBuffer.push(event.data);
            recordingStats.chunks++;
            recordingStats.totalBytes = nextTotalBytes;
            recordingStats.lastChunkTime = now;
            requestDataPendingAt = null;
            if (!firstChunkSeen) {
              firstChunkSeen = true;
              recordingStats.firstChunkSeenAt = now;
            }

            if (maxBytesValue && nextTotalBytes >= maxBytesValue) {
              recordingStats.errors.push(
                "Recording stopped after reaching size limit at " + new Date().toISOString()
              );
              setStopReason("limit");
              stopRecording();
            }
          } else {
            // Empty chunks must NOT bump lastChunkTime: that would silently
            // disarm the stall watchdog when the microphone is producing
            // zero audio, which is exactly the failure we are trying to
            // detect (Windows + Firefox produced only 287 B / 6.9 KB files).
            console.warn("Received empty data chunk");
            recordingStats.errors.push("Empty chunk received at " + new Date().toISOString());
          }
        });

        recorder.addEventListener("error", (event) => {
          const errorMsg = "MediaRecorder error: " + (event.error?.message || "Unknown error");
          console.error(errorMsg, event);
          setRecordingErrorState(errorMsg, event.error);
          recordingStats.errors.push(errorMsg);
          recordingState = "error";
          setStopReason("error");
          stopRecording();
        });

        recorder.addEventListener("stop", () => {
          try {
            if (discardRecordingOnStop) {
              return;
            }
            recordingState = "processing";

            if (recordingBuffer.length === 0) {
              const errorMsg = m.no_audio_data_captured();
              setRecordingErrorState(errorMsg);
              recordingStats.errors.push(errorMsg);
              recordingState = "error";
              setStopReason("error");
              return;
            }

            recordedMimeType =
              recorder.mimeType ||
              initialMimeType ||
              recordingBuffer.find((chunk) => chunk.type)?.type ||
              "audio/webm";
            completedRecordingAt = dayjs();
            recordedBlob = new Blob(recordingBuffer, { type: recordedMimeType });
            audioURL = URL.createObjectURL(recordedBlob);
            const reason = stopReason;
            const durationMs = Math.max(
              0,
              completedRecordingAt.diff(startedRecordingAt, "millisecond")
            );
            resetStopReason();
            onRecordingDone({
              blob: recordedBlob,
              mimeType: recordedMimeType,
              reason,
              durationMs
            });
            recordingState = "complete";
          } catch (error) {
            const errorMsg =
              "Failed to process recording: " +
              (error instanceof Error ? error.message : String(error));
            console.error(errorMsg, error);
            setRecordingErrorState(errorMsg, error);
            recordingStats.errors.push(errorMsg);
            recordingState = "error";
            setStopReason("error");
          } finally {
            releaseMediaCapture();
          }
        });

        recorder.start(TIMESLICE_MS);
        // Initialise the watchdog AFTER recorder.start() so getUserMedia
        // latency (especially on the very first permission grant) does not
        // eat into the stall budget.
        const startTimestamp = performance.now();
        recordingStats.lastChunkTime = startTimestamp;
        recordingStats.recorderMimeType = recorder.mimeType || initialMimeType;
        startedRecordingAt = dayjs();
        lastMeterUpdateAt = 0;
        lastAudibleAt = startTimestamp;
        showMicSilentHint = false;
        elapsedSeconds = 0;
        elapsedTime = "00:00";
        recordingState = "recording";
        isRecording = true;
        onRecordingStateChange(true, { origin });
        startMonitoringLoop();
        startStallChecker();
        attachVisibilityHandler();

        recorder.addEventListener("pause", () => {
          console.warn("MediaRecorder was paused unexpectedly");
          recordingStats.errors.push("Recorder paused at " + new Date().toISOString());
        });

        recorder.addEventListener("resume", () => {
          recordingStats.errors.push("Recorder resumed at " + new Date().toISOString());
        });
      } else {
        const errorMsg = "No media stream available";
        setRecordingErrorState(errorMsg);
        recordingStats.errors.push(errorMsg);
        isRecording = false;
        onRecordingStateChange(false);
        recordingState = "error";
      }
    } catch (error) {
      releaseMediaCapture();
      if (isDestroyed) {
        return;
      }
      const errorMsg =
        "Failed to start recording: " + (error instanceof Error ? error.message : String(error));
      console.error(errorMsg, error);
      setRecordingErrorState(errorMsg, error);
      recordingStats.errors.push(errorMsg);
      isRecording = false;
      onRecordingStateChange(false);
      recordingState = "error";
    }
  }

  function stopRecording() {
    stopStallChecker();
    detachVisibilityHandler();
    if (isRecording) {
      isRecording = false;
      onRecordingStateChange(false);
      recordingState = "processing";
    }

    try {
      if (mediaRecorder && mediaRecorder.state !== "inactive") {
        mediaRecorder.stop();
      }
    } catch (error) {
      const errorMsg =
        "Failed to stop recording: " + (error instanceof Error ? error.message : String(error));
      console.error(errorMsg, error);
      setRecordingErrorState(errorMsg, error);
      recordingStats.errors.push(errorMsg);
      recordingState = "error";
    }
  }

  function toggleRecording(e: Event) {
    e.preventDefault();
    if (!isRecording) {
      void startRecording("user");
    } else {
      stopRecording();
    }
  }

  // Imperative entry points for the session controller. The session needs
  // to restart the recorder after a "track ended" event without the user
  // clicking again, and the recorder must surface success/failure clearly
  // because the session schedules its next retry off the result.
  export async function startExternal(): Promise<void> {
    await startRecording("external");
    if (recordingState === "error") {
      throw new Error(recordingErrorHint ?? recordingError ?? "Failed to start recording");
    }
  }

  export function stopExternal(): void {
    stopRecording();
  }

  const onAnimationFrame = () => {
    if (analyserNode && levelBuffer.length > 0) {
      analyserNode.getFloatTimeDomainData(levelBuffer);
      let sumSquares = 0.0;
      for (const amplitude of levelBuffer) {
        sumSquares += amplitude * amplitude;
      }
      const rms = Math.sqrt(sumSquares / levelBuffer.length);
      const nextVolumeLevel = Math.min(1, rms / 0.15);
      const now = performance.now();
      if (nextVolumeLevel > MIC_ACTIVITY_THRESHOLD) {
        lastAudibleAt = now;
      }
      showMicSilentHint = isRecording && now - lastAudibleAt > MIC_SILENCE_HINT_MS;
      if (now - lastMeterUpdateAt >= METER_UPDATE_MS) {
        const attack = nextVolumeLevel > volumeLevel ? 0.55 : 0.16;
        volumeLevel = volumeLevel + (nextVolumeLevel - volumeLevel) * attack;
        lastMeterUpdateAt = now;
      }
    }
    elapsedSeconds = dayjs().diff(startedRecordingAt, "seconds");
    elapsedTime = formatElapsed(elapsedSeconds);
    animationFrameId = window.requestAnimationFrame(onAnimationFrame);
  };

  function startMonitoringLoop() {
    stopMonitoringLoop();
    animationFrameId = window.requestAnimationFrame(onAnimationFrame);
  }

  function startStallChecker() {
    stopStallChecker();
    // The stall watchdog runs on setInterval, not requestAnimationFrame:
    // browsers throttle rAF to ~1 Hz on hidden tabs, which used to make
    // any tab-switch look like an immediate stall. setInterval ticks
    // through the throttle, and the visibility handler shifts the
    // watchdog clock across the hidden interval so we do not fire on
    // return either.
    stallIntervalId = setInterval(checkStall, STALL_CHECK_INTERVAL_MS);
  }

  function stopStallChecker() {
    if (stallIntervalId !== null) {
      clearInterval(stallIntervalId);
      stallIntervalId = null;
    }
    requestDataPendingAt = null;
  }

  function checkStall() {
    if (!isRecording || !mediaRecorder || mediaRecorder.state !== "recording") return;
    // Suspend stall decisions entirely while the tab is hidden. setInterval
    // keeps ticking on hidden tabs (unlike rAF), so without this guard a
    // user who switches tabs for >7 s sees the watchdog kill an otherwise-
    // healthy recording. The visibility handler shifts the clock forward
    // when the tab returns; this just stops us deciding while we cannot
    // see what the encoder is doing.
    if (typeof document !== "undefined" && document.visibilityState === "hidden") {
      return;
    }

    const now = performance.now();
    const threshold = firstChunkSeen ? STALL_STEADY_STATE_MS : STALL_PRE_FIRST_CHUNK_MS;
    const sinceLastChunk = now - recordingStats.lastChunkTime;

    if (sinceLastChunk <= threshold) {
      requestDataPendingAt = null;
      return;
    }

    if (requestDataPendingAt === null) {
      // Try to flush any buffered data before declaring a stall: some
      // Firefox builds queue chunks past TIMESLICE_MS under load, and a
      // healthy encoder will respond to requestData() within tens of ms.
      let outcome = "ok";
      try {
        mediaRecorder.requestData();
      } catch (error) {
        outcome = error instanceof Error ? error.name : "threw";
      }
      requestDataPendingAt = now;
      recordingStats.requestDataAttempts.push({ at: now, outcome });
      return;
    }

    if (now - requestDataPendingAt < STALL_REQUEST_DATA_GRACE_MS) return;

    recordingStats.errors.push(
      "Recording stopped due to stalled data at " + new Date().toISOString()
    );
    setStopReason("stall");
    stopRecording();
  }

  function attachVisibilityHandler() {
    detachVisibilityHandler();
    visibilityHandler = () => {
      const at = performance.now();
      if (document.visibilityState === "hidden") {
        hiddenSinceMs = at;
        // Drop any in-flight requestData rescue: it would otherwise be
        // measured against a clock that's about to be shifted forward,
        // and on return checkStall would compute `now - requestDataPendingAt`
        // ≫ grace and fire an instant stall on a healthy recording.
        requestDataPendingAt = null;
        recordingStats.visibilityTransitions.push({ at, state: "hidden" });
        return;
      }
      if (document.visibilityState === "visible") {
        if (hiddenSinceMs !== null) {
          const hiddenAt = hiddenSinceMs;
          const shift = at - hiddenAt;
          // Only shift timestamps that predate the hidden window. Some
          // browsers (Firefox in particular) still deliver dataavailable
          // while hidden — if a chunk arrived during hidden, lastChunkTime
          // is already current and shifting it again would push it into
          // the future and over-forgive future stalls by one hidden span.
          if (recordingStats.lastChunkTime > 0 && recordingStats.lastChunkTime <= hiddenAt) {
            recordingStats.lastChunkTime += shift;
          }
          if (lastAudibleAt > 0 && lastAudibleAt <= hiddenAt) {
            lastAudibleAt += shift;
          }
        }
        hiddenSinceMs = null;
        requestDataPendingAt = null;
        recordingStats.visibilityTransitions.push({ at, state: "visible" });
      }
    };
    document.addEventListener("visibilitychange", visibilityHandler);
  }

  function detachVisibilityHandler() {
    if (visibilityHandler) {
      document.removeEventListener("visibilitychange", visibilityHandler);
      visibilityHandler = null;
    }
    hiddenSinceMs = null;
  }

  async function copyDiagnostics() {
    const payload = {
      capturedAt: new Date().toISOString(),
      state: recordingState,
      isRecording,
      elapsedSeconds,
      activeAudioBitsPerSecond,
      maxBytes,
      error: recordingError,
      hint: recordingErrorHint,
      stats: recordingStats
    };
    const text = JSON.stringify(payload, null, 2);
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        console.warn("Recording diagnostics:", payload);
        toast.info(m.diagnostics_logged_console());
        return;
      } catch (error) {
        console.warn("Failed to copy diagnostics to clipboard", error);
      }
    }
    console.warn("Recording diagnostics:", payload);
    toast.info(m.diagnostics_logged_console());
  }

  const formatElapsed = (seconds: number) => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);

    if (hours > 0) {
      return `${hours}:${minutes.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
    }
    return `${minutes.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  };

  function formatDurationEstimate(seconds: number): string {
    if (!Number.isFinite(seconds) || seconds <= 0) return "0 min";
    const totalMinutes = Math.max(1, Math.round(seconds / 60));
    if (totalMinutes < 60) return `${totalMinutes} min`;
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    return minutes > 0 ? `${hours} h ${minutes} min` : `${hours} h`;
  }

  async function saveCompletedRecording() {
    if (!recordedBlob) {
      toast.error(m.recording_not_found());
      return;
    }

    const file = buildRecordedAudioFile({
      blob: recordedBlob,
      mimeType: recordedMimeType || recordedBlob.type || "audio/webm",
      fileNameBase: m.recording_filename_template({
        datetime: completedRecordingAt.format("YYYY-MM-DDTHH-mm-ss[Z]")
      })
    });

    try {
      await downloadRecordedAudioFile(file);
    } catch (error) {
      console.error("Failed to save recording:", error);
      toast.error(m.recording_save_failed());
    }
  }

  async function toggleAudioPreview() {
    if (!previewAudioEl || !audioURL) return;

    if (isPreviewPlaying) {
      previewAudioEl.pause();
      isPreviewPlaying = false;
      return;
    }

    try {
      previewAudioEl.currentTime = 0;
      await previewAudioEl.play();
      isPreviewPlaying = true;
    } catch (error) {
      console.error("Failed to preview recording:", error);
      toast.error(m.recording_preview_failed());
    }
  }

  $: if (resetToken !== lastResetToken) {
    lastResetToken = resetToken;
    clearCompletedRecording();
  }

  function disposeRecorder() {
    isDestroyed = true;
    discardRecordingOnStop = true;
    clearCompletedRecording();

    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      try {
        mediaRecorder.stop();
      } catch (e) {
        console.error("Error stopping mediaRecorder during cleanup:", e);
      }
    }
    if (isRecording) {
      isRecording = false;
      onRecordingStateChange(false);
    }
    releaseMediaCapture();
  }

  onMount(() => {
    window.addEventListener("beforeunload", disposeRecorder);
    return () => window.removeEventListener("beforeunload", disposeRecorder);
  });

  onDestroy(() => {
    disposeRecorder();
  });
</script>

<div class="flex flex-col items-center justify-center gap-2">
  <div data-is-recording={isRecording} data-state={recordingState} class="recording-widget">
    <Tooltip.Root>
      <Tooltip.Trigger>
        <button
          class="record-button"
          onclick={toggleRecording}
          data-is-recording={isRecording}
          disabled={recordingState === "preparing" || recordingState === "processing"}
          aria-label={isRecording ? m.stop_recording() : m.start_recording()}
        >
          {#if !isRecording}
            <IconMicrophone />
          {:else}
            <IconStop />
          {/if}
        </button>
      </Tooltip.Trigger>
      <Tooltip.Content>{isRecording ? m.stop_recording() : m.start_recording()}</Tooltip.Content>
    </Tooltip.Root>

    {#if isRecording}
      <div class="recording-stats">
        <div class="recording-status-row">
          <span class="recording-status-dot" aria-hidden="true"></span>
          <span class="recording-status-label">{m.recording_in_progress()}</span>
          <div class="time-display">{elapsedTime}</div>
        </div>
        <div class="mic-activity-row">
          <span class="mic-activity-label">{m.recording_mic_activity()}</span>
          <div class="mic-activity-track" aria-hidden="true">
            <div class="mic-activity-fill" style="transform: scaleX({volumeLevel})"></div>
          </div>
        </div>
        {#if micRecoveryHintKey !== null}
          <div class="recording-mic-recovery-hint" role="status" aria-live="polite">
            {micRecoveryHintKey === "muted"
              ? m.recording_mic_muted_hint()
              : m.recording_mic_reconnecting_hint()}
          </div>
        {:else if showMicSilentHint}
          <div class="recording-mic-silent-hint" role="status" aria-live="polite">
            {m.recording_mic_silent_hint()}
          </div>
        {/if}
        {#if maxSizeLabel}
          <div class="size-row">
            <span class="size-display">
              {isLiveSizeEstimated ? "≈ " : ""}{formatMegabytes(visibleRecordingBytes)} /
              {maxSizeLabel} MB
            </span>
            <span class="size-rate">{m.recording_size_rate({ size: recordingRateLabel })}</span>
          </div>
          {#if estimatedRemainingLabel}
            <div class="recording-estimate">
              {m.recording_remaining_estimate({ duration: estimatedRemainingLabel })}
            </div>
          {/if}
        {/if}
      </div>
    {:else if recordingState === "preparing"}
      <div class="px-6 py-2 font-mono">{m.recording_preparing()}</div>
    {:else if recordingState === "processing"}
      <div class="px-6 py-2 font-mono">{m.processing_recording()}</div>
    {:else if recordingState === "error"}
      <div class="flex flex-col gap-2 px-4 py-3">
        <div class="flex flex-col gap-0.5">
          <div class="text-negative-stronger text-sm font-semibold">
            {m.recording_error()}
          </div>
          {#if recordingErrorHint}
            <div class="text-negative-stronger/90 text-sm leading-snug">
              {recordingErrorHint}
            </div>
          {/if}
        </div>
        {#if recordingError}
          <details class="error-details-collapse">
            <summary
              class="text-negative-default hover:text-negative-stronger cursor-pointer list-none text-xs font-medium underline underline-offset-2 transition-colors select-none"
            >
              {m.view_diagnostics()}
            </summary>
            <div
              class="bg-negative-default/15 text-negative-stronger/80 border-negative-default/25 mt-2 rounded-md border px-3 py-2 font-mono text-xs leading-relaxed break-words"
            >
              {recordingError}
            </div>
          </details>
        {:else}
          <button
            class="text-negative-default hover:text-negative-stronger cursor-pointer text-left text-xs font-medium underline underline-offset-2 transition-colors"
            onclick={copyDiagnostics}
          >
            {m.view_diagnostics()}
          </button>
        {/if}
      </div>
    {:else if audioURL}
      <div class="recording-complete">
        <div class="recording-complete-header">
          <span class="recording-complete-title">{m.recording_last_clip_ready()}</span>
          <span class="recording-complete-copy">{m.recording_ready_hint()}</span>
        </div>
        <div class="recording-complete-actions">
          <audio
            bind:this={previewAudioEl}
            src={audioURL}
            preload="metadata"
            class="sr-only"
            onended={() => {
              isPreviewPlaying = false;
            }}
            onpause={() => {
              isPreviewPlaying = false;
            }}
          ></audio>
          <Button variant="ghost" size="sm" onclick={toggleAudioPreview}>
            {#if isPreviewPlaying}
              <IconStop data-icon="inline-start" />
              {m.recording_stop_preview()}
            {:else}
              <IconPlay data-icon="inline-start" />
              {m.recording_preview()}
            {/if}
          </Button>
          <Button variant="outline" size="sm" onclick={saveCompletedRecording}>
            <IconDownload data-icon="inline-start" />
            {m.save_as_file()}
          </Button>
        </div>
      </div>
    {:else}
      <div class="idle-recording-copy">
        {#if estimatedLimitLabel && maxSizeLabel}
          <span
            >{m.recording_estimated_limit({
              duration: estimatedLimitLabel,
              size: maxSizeLabel
            })}</span
          >
        {:else}
          <span>{m.recording_record_another_hint()}</span>
        {/if}
      </div>
    {/if}
  </div>
</div>

<style lang="postcss">
  @reference "@intric/ui/styles";

  @keyframes breathe-ring {
    0%,
    100% {
      transform: scale(1);
      opacity: 0.4;
    }
    50% {
      transform: scale(1.15);
      opacity: 0;
    }
  }

  .record-button {
    @apply bg-negative-default text-on-fill hover:bg-negative-stronger relative flex h-12 w-12 items-center justify-center rounded-full transition-all duration-200;
  }

  .record-button[data-is-recording="true"] {
    @apply bg-negative-default text-on-fill hover:bg-negative-stronger;
  }

  .record-button[data-is-recording="true"]::before {
    content: "";
    position: absolute;
    inset: -4px;
    border-radius: 9999px;
    border: 2px solid currentColor;
    animation: breathe-ring 2s ease-in-out infinite;
  }

  @media (prefers-reduced-motion: reduce) {
    .record-button[data-is-recording="true"]::before {
      animation: none;
      opacity: 0;
    }
  }

  .record-button:disabled {
    @apply cursor-not-allowed opacity-50;
  }

  .recording-widget {
    @apply border-stronger bg-primary flex min-h-20 w-[min(36rem,calc(100vw-4rem))] max-w-full items-center rounded-[2rem] border p-2 shadow-lg transition-[background-color,border-color,box-shadow] duration-200 ease-out;
  }

  .recording-widget[data-is-recording="true"] {
    @apply border-negative-default/30 bg-primary shadow-xl;
  }

  .recording-widget[data-state="error"] {
    @apply bg-negative-dimmer border-negative-default/40 max-w-sm rounded-2xl border;
  }

  .recording-widget[data-state="processing"] {
    @apply bg-accent-dimmer text-accent-stronger;
  }

  .error-details-collapse summary::before {
    content: "▶ ";
    display: inline;
    font-size: 0.6em;
    vertical-align: middle;
    margin-right: 0.25em;
  }

  .error-details-collapse[open] summary::before {
    content: "▼ ";
  }

  .error-details-collapse summary::-webkit-details-marker {
    display: none;
  }

  .recording-stats {
    @apply text-primary flex min-w-0 flex-1 flex-col gap-1.5 px-4 py-1;
  }

  .recording-status-row {
    @apply flex items-center gap-2;
  }

  .time-display {
    @apply ml-auto font-mono text-sm font-semibold tabular-nums;
  }

  .recording-status-label {
    @apply text-negative-stronger text-xs font-medium tracking-[0.08em] uppercase;
  }

  .recording-status-dot {
    @apply bg-negative-default size-2 rounded-full;
  }

  .mic-activity-row {
    @apply flex items-center gap-2;
  }

  .mic-activity-label {
    @apply text-muted text-xs whitespace-nowrap;
  }

  .mic-activity-track {
    @apply bg-secondary/40 h-1.5 min-w-20 flex-1 overflow-hidden rounded-full;
  }

  .mic-activity-fill {
    @apply bg-accent-default h-full origin-left rounded-full transition-transform duration-75 ease-out;
  }

  .recording-mic-silent-hint {
    @apply text-warning-stronger text-xs leading-relaxed;
  }

  .recording-mic-recovery-hint {
    @apply text-negative-stronger text-xs leading-relaxed;
  }

  .size-row {
    @apply text-muted flex flex-wrap items-center gap-x-2 gap-y-0.5;
  }

  .size-display {
    @apply font-mono text-xs whitespace-nowrap tabular-nums;
  }

  .size-rate {
    @apply text-xs;
  }

  .idle-recording-copy {
    @apply text-muted max-w-60 px-4 py-1 text-sm leading-snug;
  }

  .recording-estimate {
    @apply text-muted text-xs;
  }

  .recording-complete {
    @apply flex min-w-0 flex-1 items-center justify-between gap-3 px-3 py-1;
  }

  .recording-complete-header {
    @apply flex min-w-0 flex-col gap-0.5;
  }

  .recording-complete-title {
    @apply text-sm font-medium;
  }

  .recording-complete-copy {
    @apply text-muted line-clamp-2 text-xs leading-relaxed;
  }

  .recording-complete-actions {
    @apply flex shrink-0 flex-wrap items-center justify-end gap-2;
  }

  @media (max-width: 420px) {
    .recording-widget {
      @apply max-w-full min-w-0 rounded-2xl;
    }

    .recording-stats {
      @apply min-w-0;
    }

    .recording-complete {
      @apply flex-col items-stretch;
    }

    .recording-complete-actions {
      @apply justify-start;
    }
  }
</style>
