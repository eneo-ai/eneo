import type { App, AppRun, UploadedFile } from "@eneo/eneo-js";
import { formatDateTime } from "$lib/core/formatting/dateTime";
import { getEneo } from "$lib/core/Eneo";
import { getEneoSocket } from "$lib/core/EneoSocket";
import { getResultTitle } from "./getResultTitle";

function isTranscribedFile(file: UploadedFile): file is UploadedFile & { transcription: string } {
  return file.transcription !== null && file.transcription !== undefined;
}

/**
 * The run shown on a result page, kept up to date over the socket until it has finished.
 *
 * __NOTE__: Can only be called during component initialisation.
 */
export function createAppRunResult(getData: () => { app: App; result: AppRun }) {
  const eneo = getEneo();
  const { subscribe } = getEneoSocket();

  let result = $derived(getData().result);
  const runId = $derived(result.id);
  const isComplete = $derived(!(result.status === "in progress" || result.status === "queued"));
  // Browser recordings can use a video container (WebM or MP4) for audio.
  const recordings = $derived(
    result.input.files.filter((file) => /^(audio|video)\//.test(file.mimetype))
  );
  const transcribedFiles = $derived(result.input.files.filter(isTranscribedFile));
  const title = $derived(getResultTitle(result));
  const textFileName = $derived(`${getData().app.name} ${formatDateTime(result.created_at)}.txt`);

  $effect(() => {
    const id = runId;
    if (isComplete) return;

    let disposed = false;
    let reading = false;
    async function refresh() {
      if (disposed || reading || document.hidden) return;
      reading = true;
      try {
        const updated = await eneo.apps.runs.get({ id });
        if (!disposed) result = updated;
      } catch {
        // A lost connection can also drop the terminal event. The next visible poll retries.
      } finally {
        reading = false;
      }
    }

    const unsubscribe = subscribe("app_run_updates", (update) => {
      if (update.id === id) void refresh();
    });
    void refresh();
    const timer = window.setInterval(refresh, 15_000);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      disposed = true;
      unsubscribe();
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  });

  return {
    get result() {
      return result;
    },
    get isComplete() {
      return isComplete;
    },
    get recordings() {
      return recordings;
    },
    get transcribedFiles() {
      return transcribedFiles;
    },
    get title() {
      return title;
    },
    /** Suggested name when saving the output or a transcription as text. */
    get textFileName() {
      return textFileName;
    }
  };
}
