<script lang="ts">
  import { IconMicrophone } from "@intric/icons/microphone";
  import { IconStop } from "@intric/icons/stop";
  import { Tooltip } from "@intric/ui";
  import { onDestroy, onMount } from "svelte";

  import dayjs from "dayjs";
  import { m } from "$lib/paraglide/messages";

  type RecordingStopReason = "manual" | "limit" | "stall" | "error";

  export let onRecordingDone: (params: {
    blob: Blob;
    mimeType: string;
    reason: RecordingStopReason;
  }) => void;
  export let onRecordingStateChange: (isRecording: boolean) => void = () => {};
  export let maxBytes: number | null = null;

  let isRecording: boolean = false;
  let startedRecordingAt = dayjs();
  let elapsedTime = "";
  let recordingError: string | null = null;
  let recordingErrorHint: string | null = null;
  let recordingState: "idle" | "recording" | "processing" | "error" | "complete" = "idle";

  // Volume level for smooth visualizer (0-1)
  let volumeLevel: number = 0;

  let mediaStream: MediaStream | null;
  let mediaStreamNode: MediaStreamAudioSourceNode | null;
  let mediaRecorder: MediaRecorder | null;
  let audioContext: AudioContext | null;
  let analyserNode: AnalyserNode | null;
  let levelBuffer = new Float32Array();

  let recordingBuffer: Blob[] = [];
  let recordedBlob: Blob | null = null;
  let audioURL: string | null = null;
  let stopReason: RecordingStopReason = "manual";
  let handleStreamEnded: ((event: Event) => void) | null = null;

  // Constants
  const TIMESLICE_MS = 10000; // Save chunks every 10 seconds
  const STALL_TIMEOUT_MS = TIMESLICE_MS * 2;

  const formatMegabytes = (bytes: number) => (bytes / (1024 * 1024)).toFixed(2);
  let maxSizeLabel: string | null = null;
  $: maxSizeLabel =
    typeof maxBytes === "number" && Number.isFinite(maxBytes) && maxBytes > 0
      ? formatMegabytes(maxBytes)
      : null;

  // Size progress percentage for limit indicator
  let sizePercent: number = 0;
  $: sizePercent =
    typeof maxBytes === "number" && Number.isFinite(maxBytes) && maxBytes > 0
      ? Math.min(100, (recordingStats.totalBytes / maxBytes) * 100)
      : 0;

  // Stats for diagnostics
  let recordingStats = {
    chunks: 0,
    totalBytes: 0,
    lastChunkTime: 0,
    errors: [] as string[]
  };

  const audioConstraints: MediaTrackConstraints = {
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
    // Store only the raw technical error for diagnostics (developer-facing)
    recordingError = error ? formatMediaError(error) : message;

    // Set user-friendly localized hint
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

  function startRecording() {
    try {
      recordingBuffer = [];
      recordingError = null;
      recordingErrorHint = null;
      recordingState = "recording";
      isRecording = true;
      stopReason = "manual";
      onRecordingStateChange(true);
      startedRecordingAt = dayjs();

      // Reset stats
      recordingStats = {
        chunks: 0,
        totalBytes: 0,
        lastChunkTime: Date.now(),
        errors: []
      };

      if (mediaStream) {
        const mimeType = MediaRecorder.isTypeSupported("audio/mp4;codecs=avc1")
          ? "audio/mp4;codecs=avc1"
          : "audio/webm;codecs=opus";

        mediaRecorder = new MediaRecorder(mediaStream, {
          mimeType
        });

        mediaRecorder.addEventListener("dataavailable", (event) => {
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

            // Update stats
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

        // Handle errors during recording
        mediaRecorder.addEventListener("error", (event) => {
          const errorMsg = "MediaRecorder error: " + (event.error?.message || "Unknown error");
          console.error(errorMsg, event);
          setRecordingErrorState(errorMsg, event.error);
          recordingStats.errors.push(errorMsg);
          recordingState = "error";
          stopReason = "error";
          stopRecording();
        });

        mediaRecorder.addEventListener("stop", () => {
          try {
            recordingState = "processing";

            if (recordingBuffer.length === 0) {
              const errorMsg = m.no_audio_data_captured();
              setRecordingErrorState(errorMsg);
              recordingStats.errors.push(errorMsg);
              recordingState = "error";
              stopReason = "error";
              return;
            }

            recordedBlob = new Blob(recordingBuffer, { type: mimeType });
            audioURL = URL.createObjectURL(recordedBlob);
            const reason = stopReason;
            stopReason = "manual";
            onRecordingDone({ blob: recordedBlob, mimeType, reason });
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
          }
        });

        mediaRecorder.start(TIMESLICE_MS);

        // Add event listeners to detect browser issues
        mediaRecorder.addEventListener("pause", () => {
          console.warn("MediaRecorder was paused unexpectedly");
          recordingStats.errors.push("Recorder paused at " + new Date().toISOString());
        });

        mediaRecorder.addEventListener("resume", () => {
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
    }

    try {
      // Only call stop if the mediaRecorder is actually recording
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
      startRecording();
    } else {
      stopRecording();
    }
  }

  const onAnimationFrame = () => {
    // Update volume level for visualizer
    if (analyserNode && levelBuffer.length > 0) {
      analyserNode.getFloatTimeDomainData(levelBuffer);
      let sumSquares = 0.0;
      for (const amplitude of levelBuffer) {
        sumSquares += amplitude * amplitude;
      }
      // Normalize RMS to 0-1 range - speech RMS is typically 0.01-0.1
      // Using 0.15 as max gives good sensitivity for speech
      const rms = Math.sqrt(sumSquares / levelBuffer.length);
      volumeLevel = Math.min(1, rms / 0.15);
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
    elapsedTime = formatElapsed(dayjs().diff(startedRecordingAt, "seconds"));
    window.requestAnimationFrame(onAnimationFrame);
  };

  const formatElapsed = (seconds: number) => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);

    if (hours > 0) {
      return `${hours}:${minutes.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
    }
    return `${minutes.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  };

  onMount(async () => {
    try {
      mediaStream = await requestAudioStream();

      const streamEndedHandler = (_event: Event) => {
        if (!isRecording) return;
        const errorMsg = m.recording_device_disconnected();
        setRecordingErrorState(errorMsg);
        recordingStats.errors.push(errorMsg + " at " + new Date().toISOString());
        stopReason = "error";
        stopRecording();
      };

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
      window.requestAnimationFrame(onAnimationFrame);
    } catch (error) {
      await collectMediaDiagnostics("Failed to access microphone", error);
      const errorMsg = m.failed_to_access_microphone({
        error: formatMediaError(error)
      });
      console.error(errorMsg, error);
      setRecordingErrorState(errorMsg, error);
      recordingState = "error";
    }
  });

  onDestroy(() => {
    // Clean up any objectURLs to prevent memory leaks
    if (audioURL) {
      URL.revokeObjectURL(audioURL);
    }

    // Stop all media
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      try {
        mediaRecorder.stop();
      } catch (e) {
        console.error("Error stopping mediaRecorder during cleanup:", e);
      }
    }

    if (mediaStream && handleStreamEnded) {
      const streamEndedHandler = handleStreamEnded;
      mediaStream.removeEventListener("inactive", streamEndedHandler);
      mediaStream.getAudioTracks().forEach((track) => {
        track.removeEventListener("ended", streamEndedHandler);
      });
    }

    mediaStream?.getAudioTracks().forEach((track) => {
      track.stop();
    });

    mediaStream = null;
  });
</script>

<div class="flex flex-col items-center justify-center gap-2">
  <div data-is-recording={isRecording} data-state={recordingState} class="recording-widget">
    <Tooltip text={isRecording ? m.stop_recording() : m.start_recording()}>
      <button
        class="record-button"
        on:click={toggleRecording}
        data-is-recording={isRecording}
        disabled={recordingState === "processing"}
      >
        {#if !isRecording}
          <IconMicrophone />
        {:else}
          <IconStop />
        {/if}
      </button>
    </Tooltip>

    {#if isRecording}
      <div class="recording-stats">
        <div class="stats-row">
          <div class="time-display">{elapsedTime}</div>
          <div class="volume-indicator">
            <div class="volume-bar" style="transform: scaleX({volumeLevel})"></div>
          </div>
        </div>
        {#if maxSizeLabel}
          <div class="size-row">
            <span class="size-display">{formatMegabytes(recordingStats.totalBytes)} / {maxSizeLabel} MB</span>
            <div class="size-progress-track">
              <div class="size-progress-bar" style="width: {sizePercent}%"></div>
            </div>
          </div>
        {/if}
      </div>
    {:else if recordingState === "processing"}
      <div class="px-6 py-2 font-mono">{m.processing_recording()}</div>
    {:else if recordingState === "error"}
      <div class="flex flex-col gap-2 px-4 py-3">
        <div class="flex flex-col gap-0.5">
          <div class="text-sm font-semibold text-negative-stronger">
            {m.recording_error()}
          </div>
          {#if recordingErrorHint}
            <div class="text-sm leading-snug text-negative-stronger/90">
              {recordingErrorHint}
            </div>
          {/if}
        </div>
        {#if recordingError}
          <details class="error-details-collapse">
            <summary class="cursor-pointer select-none list-none text-xs font-medium text-negative-default hover:text-negative-stronger transition-colors underline underline-offset-2">
              {m.view_diagnostics()}
            </summary>
            <div class="mt-2 rounded-md px-3 py-2 font-mono text-xs leading-relaxed break-words bg-negative-default/15 text-negative-stronger/80 border border-negative-default/25">
              {recordingError}
            </div>
          </details>
        {:else}
          <button
            class="cursor-pointer text-xs font-medium underline underline-offset-2 transition-colors text-negative-default hover:text-negative-stronger text-left"
            on:click={() => {
              console.warn("Recording diagnostics:", recordingStats);
              alert(m.diagnostics_logged_console());
            }}
          >
            {m.view_diagnostics()}
          </button>
        {/if}
      </div>
    {:else if audioURL}
      <audio
        controls
        preload="metadata"
        src={audioURL}
        class="audio-player"
        dir="ltr"
      ></audio>
    {:else}
      <div class="volume-container">
        <div class="volume-track">
          <div class="volume-level" style="transform: scaleX({volumeLevel})"></div>
        </div>
      </div>
    {/if}
  </div>
</div>

<style lang="postcss">
  @reference "@intric/ui/styles";

  /* Breathing pulse animation for active recording */
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

  /* Subtle glow for recording state */
  @keyframes subtle-glow {
    0%,
    100% {
      box-shadow:
        0 10px 15px -3px rgb(0 0 0 / 0.1),
        0 4px 6px -4px rgb(0 0 0 / 0.1);
    }
    50% {
      box-shadow:
        0 10px 15px -3px rgb(0 0 0 / 0.1),
        0 4px 6px -4px rgb(0 0 0 / 0.1),
        0 0 20px 2px rgb(239 68 68 / 0.15);
    }
  }

  .record-button {
    @apply bg-negative-default text-on-fill hover:bg-negative-stronger relative flex h-12 w-12 items-center justify-center rounded-full transition-all duration-200;
  }

  .record-button[data-is-recording="true"] {
    @apply bg-primary text-negative-stronger hover:bg-negative-dimmer hover:text-negative-stronger;
  }

  /* Breathing pulse ring during recording */
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
    .recording-widget[data-is-recording="true"] {
      animation: none;
    }
  }

  .record-button:disabled {
    @apply cursor-not-allowed opacity-50;
  }

  .recording-widget {
    @apply border-stronger bg-primary flex items-center rounded-full border p-2 shadow-lg transition-all duration-300 ease-out;
  }

  .recording-widget[data-is-recording="true"] {
    @apply bg-negative-default text-on-fill;
    animation: subtle-glow 2s ease-in-out infinite;
  }

  .recording-widget[data-state="error"] {
    @apply bg-negative-dimmer border-negative-default/40 rounded-2xl max-w-sm border;
  }

  .recording-widget[data-state="processing"] {
    @apply bg-accent-dimmer text-on-fill;
  }

  /* Custom disclosure marker for details element */
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

  /* Recording stats display - compact layout */
  .recording-stats {
    @apply flex flex-col gap-1 px-4 py-1 font-mono;
  }

  .stats-row {
    @apply flex items-center gap-3;
  }

  .time-display {
    @apply text-base font-medium tabular-nums;
  }

  /* Live volume indicator during recording */
  .volume-indicator {
    @apply h-2 w-16 overflow-hidden rounded-full bg-white/20;
  }

  .volume-bar {
    @apply h-full origin-left rounded-full;
    background: linear-gradient(90deg, #4ade80 0%, #facc15 70%, #f87171 100%);
    transition: transform 50ms linear;
  }

  .size-row {
    @apply flex items-center gap-2;
  }

  .size-display {
    @apply text-xs opacity-80 whitespace-nowrap;
  }

  /* Size limit progress bar */
  .size-progress-track {
    @apply h-1 flex-1 overflow-hidden rounded-full bg-white/20;
  }

  .size-progress-bar {
    @apply h-full rounded-full bg-white/60 transition-[width] duration-300 ease-out;
  }

  /* Volume visualizer in idle state */
  .volume-container {
    @apply flex items-center justify-center px-4;
  }

  .volume-track {
    @apply h-3 w-20 overflow-hidden rounded-full;
    background: linear-gradient(90deg, #e5e7eb 0%, #d1d5db 100%);
  }

  :global(.dark) .volume-track {
    background: linear-gradient(90deg, #374151 0%, #4b5563 100%);
  }

  .volume-level {
    @apply h-full origin-left rounded-full;
    background: linear-gradient(90deg, #22c55e 0%, #84cc16 50%, #eab308 100%);
    transition: transform 50ms linear;
  }

  /* Audio player - ensure LTR rendering and consistent styling */
  .audio-player {
    @apply border-stronger ml-2 h-12 rounded-full border shadow-sm;
    direction: ltr !important;
    unicode-bidi: bidi-override;
  }

  /* Force LTR on all audio player internal elements */
  .audio-player::-webkit-media-controls {
    direction: ltr !important;
  }

  .audio-player::-webkit-media-controls-panel {
    direction: ltr !important;
  }

  .audio-player::-webkit-media-controls-timeline {
    direction: ltr !important;
  }

  .audio-player::-webkit-media-controls-current-time-display,
  .audio-player::-webkit-media-controls-time-remaining-display {
    direction: ltr !important;
  }
</style>
