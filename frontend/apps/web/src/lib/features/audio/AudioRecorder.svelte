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
  import { downloadRecordedAudioFile } from "./downloadRecordedAudioFile";

  type RecordingStopReason = "manual" | "limit" | "stall" | "error";

  export let onRecordingDone: (params: {
    blob: Blob;
    mimeType: string;
    reason: RecordingStopReason;
  }) => void;
  export let onRecordingStateChange: (isRecording: boolean) => void = () => {};
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

  const TIMESLICE_MS = 2000;
  const STALL_TIMEOUT_MS = TIMESLICE_MS * 2;
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
    errors: [] as string[]
  };

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
      errors: []
    };
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
      stopReason = "error";
      stopRecording();
    };

    mediaStream = nextStream;
    handleStreamEnded = streamEndedHandler;
    mediaStream.addEventListener("inactive", streamEndedHandler);
    mediaStream.getAudioTracks().forEach((track) => {
      track.addEventListener("ended", streamEndedHandler);
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

  async function startRecording() {
    try {
      recordingBuffer = [];
      recordedBlob = null;
      recordedMimeType = "";
      recordingError = null;
      recordingErrorHint = null;
      recordingState = "preparing";
      stopReason = "manual";
      discardRecordingOnStop = false;
      clearAudioPreviewUrl();

      recordingStats = {
        chunks: 0,
        totalBytes: 0,
        lastChunkTime: Date.now(),
        errors: []
      };

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
            const maxBytesValue =
              typeof maxBytes === "number" && Number.isFinite(maxBytes) && maxBytes > 0
                ? maxBytes
                : null;
            const nextTotalBytes = recordingStats.totalBytes + event.data.size;

            if (maxBytesValue && nextTotalBytes > maxBytesValue) {
              recordingStats.errors.push(
                "Recording stopped after reaching size limit at " + new Date().toISOString()
              );
              stopReason = "limit";
              stopRecording();
              return;
            }

            recordingBuffer.push(event.data);

            recordingStats.chunks++;
            recordingStats.totalBytes = nextTotalBytes;
            recordingStats.lastChunkTime = Date.now();

            if (maxBytesValue && nextTotalBytes >= maxBytesValue) {
              recordingStats.errors.push(
                "Recording stopped after reaching size limit at " + new Date().toISOString()
              );
              stopReason = "limit";
              stopRecording();
            }
          } else {
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
          stopReason = "error";
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
              stopReason = "error";
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
            stopReason = "manual";
            onRecordingDone({ blob: recordedBlob, mimeType: recordedMimeType, reason });
            recordingState = "complete";
          } catch (error) {
            const errorMsg =
              "Failed to process recording: " +
              (error instanceof Error ? error.message : String(error));
            console.error(errorMsg, error);
            setRecordingErrorState(errorMsg, error);
            recordingStats.errors.push(errorMsg);
            recordingState = "error";
            stopReason = "error";
          } finally {
            releaseMediaCapture();
          }
        });

        recorder.start(TIMESLICE_MS);
        startedRecordingAt = dayjs();
        lastMeterUpdateAt = 0;
        lastAudibleAt = Date.now();
        showMicSilentHint = false;
        elapsedSeconds = 0;
        elapsedTime = "00:00";
        recordingState = "recording";
        isRecording = true;
        onRecordingStateChange(true);
        startMonitoringLoop();

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
      void startRecording();
    } else {
      stopRecording();
    }
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
      const now = Date.now();
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

    if (
      isRecording &&
      recordingStats.lastChunkTime > 0 &&
      Date.now() - recordingStats.lastChunkTime > STALL_TIMEOUT_MS
    ) {
      recordingStats.errors.push(
        "Recording stopped due to stalled data at " + new Date().toISOString()
      );
      stopReason = "stall";
      stopRecording();
    }
    elapsedSeconds = dayjs().diff(startedRecordingAt, "seconds");
    const maxBytesValue =
      typeof maxBytes === "number" && Number.isFinite(maxBytes) && maxBytes > 0 ? maxBytes : null;
    if (
      isRecording &&
      maxBytesValue &&
      recordingStats.chunks === 0 &&
      estimateRecordingBytes(elapsedSeconds, activeAudioBitsPerSecond) >= maxBytesValue
    ) {
      recordingStats.errors.push(
        "Recording stopped after estimated size reached limit at " + new Date().toISOString()
      );
      stopReason = "limit";
      stopRecording();
    }
    elapsedTime = formatElapsed(elapsedSeconds);
    animationFrameId = window.requestAnimationFrame(onAnimationFrame);
  };

  function startMonitoringLoop() {
    stopMonitoringLoop();
    animationFrameId = window.requestAnimationFrame(onAnimationFrame);
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
        {#if showMicSilentHint}
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
            onclick={() => {
              console.warn("Recording diagnostics:", recordingStats);
              toast.info(m.diagnostics_logged_console());
            }}
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
