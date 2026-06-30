import { createContext } from "$lib/core/context";
import { createResourceEditor } from "$lib/core/editing/ResourceEditor";
import type { Eneo, App } from "@eneo/eneo-js";

const [getAppEditor, setAppEditor] = createContext<ReturnType<typeof initAppEditor>>("Edit an App");

/**
 * Initialise the ResourceEditor in its context.
 * Retrieve it via `getAppEditor()`
 */
function initAppEditor(data: { app: App; eneo: Eneo; onUpdateDone?: (app: App) => void }) {
  const editor = createResourceEditor({
    eneo: data.eneo,
    resource: data.app,
    defaults: {
      prompt: { description: "", text: "" }
    },
    editableFields: {
      name: true,
      description: true,
      completion_model: { id: true },
      completion_model_kwargs: true,
      transcription_model: { id: true },
      attachments: ["id"],
      prompt: { description: true, text: true },
      input_fields: ["type", "description"],
      data_retention_days: true
    },
    manageAttachements: "attachments",
    updateResource: async (resource, changes) => {
      const updated = await data.eneo.apps.update({ app: resource, update: changes });
      data.onUpdateDone?.(updated);
      return updated;
    }
  });
  setAppEditor(editor);
  return editor;
}
export { initAppEditor, getAppEditor };
