import { createContext } from "$lib/core/context";
import { createResourceEditor } from "$lib/core/editing/ResourceEditor";
import { mergeParentSkillBindings } from "$lib/features/skills/mergeParentSkillBindings";
import type { Eneo, App, SkillBindingReferenceInput } from "@eneo/eneo-js";

const [getAppEditor, setAppEditor] = createContext<ReturnType<typeof initAppEditor>>("Edit an App");

/**
 * Initialise the ResourceEditor in its context.
 * Retrieve it via `getAppEditor()`
 */
function initAppEditor(data: {
  app: App;
  skillBindings?: SkillBindingReferenceInput[];
  eneo: Eneo;
  onUpdateDone?: (app: App) => void;
}) {
  const editor = createResourceEditor({
    eneo: data.eneo,
    resource: {
      ...data.app,
      skill_bindings: data.skillBindings ?? []
    },
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
      skill_bindings: ["skill_id", "skill_revision_id"],
      input_fields: ["type", "description"],
      data_retention_days: true
    },
    manageAttachements: "attachments",
    updateResource: async (resource, changes) => {
      const updated = await data.eneo.apps.update({ app: resource, update: changes });
      data.onUpdateDone?.(updated);
      return mergeParentSkillBindings(updated, resource.skill_bindings, changes);
    }
  });
  setAppEditor(editor);
  return editor;
}
export { initAppEditor, getAppEditor };
