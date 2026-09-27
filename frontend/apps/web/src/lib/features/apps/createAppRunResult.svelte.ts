import type { App, AppRun, UploadedFile } from "@eneo/eneo-js";
import { formatDateTime } from "$lib/core/formatting/dateTime";
import { onMount } from "svelte";
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

  let result = $state(getData().result);
  const isComplete = $derived(!(result.status === "in progress" || result.status === "queued"));
  const transcribedFiles = $derived(
    result.output ? result.input.files.filter(isTranscribedFile) : []
  );
  const title = $derived(getResultTitle(result));
  const textFileName = $derived(`${getData().app.name} ${formatDateTime(result.created_at)}.txt`);

  onMount(() => {
    if (isComplete) return;

    const unsubscribe = subscribe("app_run_updates", async (update) => {
      if (update.id === getData().result.id) {
        result = await eneo.apps.runs.get(result);
      }
    });

    // The run can switch from "queued" to "in progress" after the load function fetched it but
    // before the subscription above exists, so fetch it once more to not miss that update.
    if (result.status === "queued") {
      eneo.apps.runs.get(result).then((updatedResult) => {
        result = updatedResult;
      });
    }

    return unsubscribe;
  });

  return {
    get result() {
      return result;
    },
    get isComplete() {
      return isComplete;
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
