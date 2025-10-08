<script lang="ts">
  import { IconMicrophone } from "@intric/icons/microphone";
  import { IconStop } from "@intric/icons/stop";
  import { Tooltip } from "@intric/ui";
  import { onDestroy, onMount } from "svelte";

  import dayjs from "dayjs";
  import { m } from "$lib/paraglide/messages";

  export let onRecordingDone: (params: { blob: Blob; mimeType: string }) => void;

  let isRecording: boolean = false;
  let startedRecordingAt = dayjs();
  let elapsedTime = "";
  let volumeMeter: HTMLMeterElement | undefined;
  let recordingError: string | null = null;
  let recordingState: "idle" | "recording" | "processing" | "error" | "complete" = "idle";

  let mediaStream: MediaStream | null;
  let mediaStreamNode: MediaStreamAudioSourceNode | null;
  let mediaRecorder: MediaRecorder | null;
  let audioContext: AudioContext | null;
  let analyserNode: AnalyserNode | null;
  let levelBuffer = new Float32Array();

  let recordingBuffer: Blob[] = [];
  let recordedBlob: Blob | null = null;
  let audioURL: string | null = null;

  // Constants
  const TIMESLICE_MS = 10000; // Save chunks every 10 seconds

  // Stats for diagnostics
  let recordingStats = {
    chunks: 0,
    totalBytes: 0,
    lastChunkTime: 0,
    errors: [] as string[]
  };

  function startRecording() {
    try {
      recordingBuffer = [];
      recordingError = null;
      recordingState = "recording";
      isRecording = true;
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
            recordingBuffer.push(event.data);

            // Update stats
            recordingStats.chunks++;
            recordingStats.totalBytes += event.data.size;
            recordingStats.lastChunkTime = Date.now();
          } else {
            console.warn("Received empty data chunk");
            recordingStats.errors.push("Empty chunk received at " + new Date().toISOString());
          }
        });

        // Handle errors during recording
        mediaRecorder.addEventListener("error", (event) => {
          const errorMsg = "MediaRecorder error: " + (event.error?.message || "Unknown error");
          console.error(errorMsg, event);
          recordingError = errorMsg;
          recordingStats.errors.push(errorMsg);
          recordingState = "error";
          stopRecording();
        });

        mediaRecorder.addEventListener("stop", () => {
          try {
            recordingState = "processing";

            if (recordingBuffer.length === 0) {
              const errorMsg = m.no_audio_data_captured();
              recordingError = errorMsg;
              recordingStats.errors.push(errorMsg);
              recordingState = "error";
              return;
            }

            recordedBlob = new Blob(recordingBuffer, { type: mimeType });
            audioURL = URL.createObjectURL(recordedBlob);
            onRecordingDone({ blob: recordedBlob, mimeType });
            recordingState = "complete";
          } catch (error) {
            const errorMsg =
              "Failed to process recording: " +
              (error instanceof Error ? error.message : String(error));
            console.error(errorMsg, error);
            recordingError = errorMsg;
            recordingStats.errors.push(errorMsg);
            recordingState = "error";
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
        recordingError = errorMsg;
        recordingStats.errors.push(errorMsg);
        isRecording = false;
        recordingState = "error";
      }
    } catch (error) {
      const errorMsg =
        "Failed to start recording: " + (error instanceof Error ? error.message : String(error));
      console.error(errorMsg, error);
      recordingError = errorMsg;
      recordingStats.errors.push(errorMsg);
      isRecording = false;
      recordingState = "error";
    }
  }

  function stopRecording() {
    isRecording = false;

    try {
      // Only call stop if the mediaRecorder is actually recording
      if (mediaRecorder && mediaRecorder.state !== "inactive") {
        mediaRecorder.stop();
      }
    } catch (error) {
      const errorMsg =
        "Failed to stop recording: " + (error instanceof Error ? error.message : String(error));
      console.error(errorMsg, error);
      recordingError = errorMsg;
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
    if (volumeMeter) {
      analyserNode?.getFloatTimeDomainData(levelBuffer);
      let sumSquares = 0.0;
      for (const amplitude of levelBuffer) {
        sumSquares += amplitude * amplitude;
      }
      volumeMeter.value = Math.sqrt(sumSquares / levelBuffer.length);
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
      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          noiseSuppression: true,
          echoCancellation: true,
          autoGainControl: true
        }
      });

      audioContext = new AudioContext();
      analyserNode = audioContext.createAnalyser();
      levelBuffer = new Float32Array(analyserNode.fftSize);
      mediaStreamNode = audioContext.createMediaStreamSource(mediaStream);
      mediaStreamNode.connect(analyserNode);
      window.requestAnimationFrame(onAnimationFrame);
    } catch (error) {
      const errorMsg =
        m.failed_to_access_microphone({ error: error instanceof Error ? error.message : String(error) });
      console.error(errorMsg, error);
      recordingError = errorMsg;
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
      <div class="px-6 py-2 font-mono">
        <div>{m.time_label()}{elapsedTime}</div>
        <div class="text-xs">
          {(recordingStats.totalBytes / (1024 * 1024)).toFixed(2)}
          MB
        </div>
      </div>
    {:else if recordingState === "processing"}
      <div class="px-6 py-2 font-mono">{m.processing_recording()}</div>
    {:else if recordingState === "error"}
      <div class="error-message px-6 py-2">
        <div>{m.recording_error()}</div>
        <div class="text-xs">{recordingError}</div>
        <button
          class="cursor-pointer text-xs underline"
          on:click={() => {
            console.warn("Recording diagnostics:", recordingStats);
            alert(m.diagnostics_logged_console());
          }}
        >
          {m.view_diagnostics()}
        </button>
      </div>
    {:else if audioURL}
      <audio controls src={audioURL} class="border-stronger ml-2 h-12 rounded-full border shadow-sm"
      ></audio>
    {:else}
      <div class="flex flex-col items-center justify-center px-6">
        <meter bind:this={volumeMeter} min="0" high="0.7" optimum="0.5" max="0.8" value="0"></meter>
      </div>
    {/if}
  </div>
</div>

<style lang="postcss">
  @reference "@intric/ui/styles";
  .record-button {
    @apply bg-negative-default text-on-fill hover:bg-negative-stronger flex h-12 w-12 items-center justify-center rounded-full;
  }

  .record-button[data-is-recording="true"] {
    @apply bg-primary text-negative-stronger hover:bg-negative-dimmer hover:text-negative-stronger;
  }

  .record-button:disabled {
    @apply cursor-not-allowed opacity-50;
  }

  .recording-widget {
    @apply border-stronger bg-primary flex items-center rounded-full border p-2 shadow-lg;
  }

  .recording-widget[data-is-recording="true"] {
    @apply bg-negative-default text-on-fill;
  }

  .recording-widget[data-state="error"] {
    @apply bg-negative-stronger text-on-fill rounded-lg;
  }

  .recording-widget[data-state="processing"] {
    @apply bg-accent-dimmer text-on-fill;
  }

  .error-message {
    @apply text-on-fill text-sm;
  }

  meter::-webkit-meter-inner-element {
    @apply !h-4 overflow-clip rounded-full;
  }

  meter::-webkit-meter-bar {
    @apply !h-4 overflow-clip rounded-full;
  }
</style>
