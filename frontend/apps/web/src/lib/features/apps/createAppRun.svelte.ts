import type { App, AppRun } from "@eneo/eneo-js";
import { fromStore, toStore } from "svelte/store";
import { page } from "$app/state";
import { toast } from "$lib/components/toast";
import { getEneo } from "$lib/core/Eneo";
import { toastError } from "$lib/core/errors";
import { initAttachmentManager } from "$lib/features/attachments/AttachmentManager";
import { getAppAttachmentRulesStore } from "$lib/features/attachments/getAttachmentRules";
import { m } from "$lib/paraglide/messages";

/**
 * Inputs and submission for a run of the app in the current page data. Sets up the
 * `AttachmentManager` the input components read, with rules that follow the app, so it is not
 * recreated when the page switches app.
 *
 * __NOTE__: Can only be called during component initialisation.
 */
export function createAppRun(onCreated: (run: AppRun, app: App) => void) {
  const eneo = getEneo();
  const app = $derived(page.data.app as App);

  const {
    clearUploads,
    state: { attachments }
  } = initAttachmentManager({
    eneo,
    options: { rules: getAppAttachmentRulesStore(toStore(() => app)) }
  });
  const currentAttachments = fromStore(attachments);

  let text = $state<string | null>(null);
  const files = $derived(
    currentAttachments.current.map((a) => a.fileRef).filter((file) => file !== undefined)
  );
  const hasData = $derived(files.length > 0 || !!text);
  const dragDropEnabled = $derived(app.input_fields.some((field) => field.type.includes("upload")));

  let isDragging = $state(false);
  let isSubmitting = $state(false);

  async function submit() {
    if (!hasData) {
      toast.warning(m.input_required_to_run_app());
      return;
    }

    try {
      isSubmitting = true;
      const run = await eneo.apps.runs.create({
        app,
        inputs: { files: files.map(({ id }) => ({ id })), text }
      });
      text = null;
      clearUploads();
      isSubmitting = false;
      onCreated(run, app);
    } catch (err) {
      console.error(err);
      toastError(err);
      isSubmitting = false;
    }
  }

  return {
    get app() {
      return app;
    },
    get text() {
      return text;
    },
    set text(value: string | null) {
      text = value;
    },
    get hasData() {
      return hasData;
    },
    get isSubmitting() {
      return isSubmitting;
    },
    get isDragging() {
      return isDragging;
    },
    set isDragging(value: boolean) {
      isDragging = value;
    },
    /** `dragenter` handler for the view: shows the drop area when the app takes uploads. */
    onDragEnter(event: DragEvent) {
      if (!dragDropEnabled) return;
      event.preventDefault();
      isDragging = true;
    },
    submit
  };
}
