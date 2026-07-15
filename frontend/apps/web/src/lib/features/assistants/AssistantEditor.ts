import { createContext } from "$lib/core/context";
import { createResourceEditor } from "$lib/core/editing/ResourceEditor";
import { mergeParentSkillBindings } from "$lib/features/skills/mergeParentSkillBindings";
import type { Eneo, Assistant, SkillBindingReferenceInput } from "@eneo/eneo-js";

const [getAssistantEditor, setAssistantEditor] =
  createContext<ReturnType<typeof initAssistantEditor>>("Edit an Assistant");

/**
 * Initialise the ResourceEditor in its context.
 * Retrieve it via `getAssistantEditor()`
 */
function initAssistantEditor(data: {
  assistant: Assistant;
  skillBindings?: SkillBindingReferenceInput[];
  eneo: Eneo;
  onUpdateDone?: (assistant: Assistant) => void;
}) {
  const editor = createResourceEditor({
    eneo: data.eneo,
    resource: {
      ...data.assistant,
      skill_bindings: data.skillBindings ?? []
    },
    defaults: {
      prompt: { description: "", text: "" },
      insight_enabled: false,
      mcp_tools: []
    },
    updateResource: async (resource, changes) => {
      const updated = await data.eneo.assistants.update({
        assistant: resource,
        update: changes as Parameters<typeof data.eneo.assistants.update>[0]["update"]
      });
      data.onUpdateDone?.(updated);
      return mergeParentSkillBindings(updated, resource.skill_bindings, changes);
    },
    editableFields: {
      name: true,
      description: true,
      insight_enabled: true,
      completion_model: { id: true },
      completion_model_kwargs: true,
      prompt: { description: true, text: true },
      websites: ["id"],
      groups: ["id"],
      integration_knowledge_list: ["id"],
      mcp_servers: ["id"],
      mcp_tools: ["tool_id", "is_enabled"] as unknown as true,
      skill_bindings: ["skill_id", "skill_revision_id"],
      attachments: ["id"],
      data_retention_days: true
    } as Record<string, unknown>,
    manageAttachements: "attachments"
  });
  setAssistantEditor(editor);
  return editor;
}
export { initAssistantEditor, getAssistantEditor };
