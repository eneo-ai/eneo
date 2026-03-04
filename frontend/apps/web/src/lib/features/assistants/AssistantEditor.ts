import { createContext } from "$lib/core/context";
import { createResourceEditor } from "$lib/core/editing/ResourceEditor";
import type { Intric, Assistant } from "@intric/intric-js";

const [getAssistantEditor, setAssistantEditor] =
  createContext<ReturnType<typeof initAssistantEditor>>("Edit an Assistant");

/**
 * Initialise the ResourceEditor in its context.
 * Retrieve it via `getAssistantEditor()`
 */
function initAssistantEditor(data: {
  assistant: Assistant;
  intric: Intric;
  onUpdateDone?: (assistant: Assistant) => void;
}) {
  const editor = createResourceEditor({
    intric: data.intric,
    resource: data.assistant,
    defaults: {
      prompt: { description: "", text: "" },
      insight_enabled: false,
      mcp_tools: []
    },
    updateResource: async (resource, changes) => {
      const updated = await data.intric.assistants.update({ assistant: resource, update: changes });
      data.onUpdateDone?.(updated);
      return updated;
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
      mcp_tools: ["tool_id", "is_enabled"],
      attachments: ["id"],
      data_retention_days: true,
      rag_context_type: true,
      rag_context_value: true
    },
    manageAttachements: "attachments"
  });
  setAssistantEditor(editor);
  return editor;
}
export { initAssistantEditor, getAssistantEditor };
