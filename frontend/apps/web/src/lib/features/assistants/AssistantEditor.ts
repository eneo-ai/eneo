import { createContext } from "$lib/core/context";
import { createResourceEditor } from "$lib/core/editing/ResourceEditor";
import { getLocale } from "$lib/paraglide/runtime";
import type { Intric, Assistant } from "@intric/intric-js";

const [getAssistantEditor, setAssistantEditor] =
  createContext<ReturnType<typeof initAssistantEditor>>("Edit an Assistant");

type CapabilityItem = { capability_id: string; input: Record<string, unknown> };

/** Map the ResourceEditor change-diff to ordered config-capability calls so the
 * settings page Save commits through the SAME capability layer as the chat plane.
 * `published` and `icon_id` are committed by their own components, not via Save. */
function buildCapabilityItems(changes: Record<string, unknown>): CapabilityItem[] {
  const items: CapabilityItem[] = [];
  const has = (key: string) => key in changes;
  const ids = (key: string) =>
    ((changes[key] as Array<{ id: string }>) ?? []).map((item) => item.id);

  if (has("name"))
    items.push({ capability_id: "assistant.set_name", input: { name: changes.name } });
  if (has("description"))
    items.push({
      capability_id: "assistant.set_description",
      input: { description: changes.description }
    });

  const model = changes.completion_model as { id?: string } | undefined;
  if (has("completion_model") && model?.id)
    items.push({
      capability_id: "assistant.set_completion_model",
      input: { completion_model_id: model.id }
    });
  if (has("completion_model_kwargs"))
    items.push({
      capability_id: "assistant.set_behavior",
      input: { ...((changes.completion_model_kwargs as Record<string, unknown>) ?? {}) }
    });

  const prompt = changes.prompt as { text?: string; description?: string | null } | undefined;
  if (has("prompt"))
    items.push({
      capability_id: "assistant.set_prompt",
      input: { text: prompt?.text ?? "", description: prompt?.description ?? null }
    });

  // Knowledge (collections/websites/integration/MCP-server membership) is one
  // replace-all set_knowledge call carrying whichever fields changed.
  const knowledge: Record<string, unknown> = {};
  if (has("groups")) knowledge.collection_ids = ids("groups");
  if (has("websites")) knowledge.website_ids = ids("websites");
  if (has("integration_knowledge_list"))
    knowledge.integration_knowledge_ids = ids("integration_knowledge_list");
  if (has("mcp_servers")) knowledge.mcp_server_ids = ids("mcp_servers");
  if (Object.keys(knowledge).length)
    items.push({ capability_id: "assistant.set_knowledge", input: knowledge });

  if (has("mcp_tools"))
    items.push({
      capability_id: "assistant.set_mcp_tools",
      input: { mcp_tools: changes.mcp_tools ?? [] }
    });
  if (has("attachments"))
    items.push({
      capability_id: "assistant.set_attachments",
      input: { attachment_ids: ids("attachments") }
    });
  if (has("data_retention_days"))
    items.push({
      capability_id: "assistant.set_data_retention_days",
      input: { data_retention_days: changes.data_retention_days }
    });
  if (has("insight_enabled"))
    items.push({
      capability_id: "assistant.set_insight_enabled",
      input: { insight_enabled: changes.insight_enabled }
    });

  return items;
}

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
      // Commit through the capability layer (atomic batch) instead of the REST
      // update, so the page and the chat share one path (permission + audit). An
      // empty batch is a safe no-op that just returns the current assistant.
      const items = buildCapabilityItems(changes as Record<string, unknown>);
      const updated = await data.intric.assistants.commitConfigCapabilities({
        assistant: resource,
        items,
        language: getLocale()
      });
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
      mcp_tools: ["tool_id", "is_enabled"] as unknown as true,
      attachments: ["id"],
      data_retention_days: true
    } as Record<string, unknown>,
    manageAttachements: "attachments"
  });
  setAssistantEditor(editor);
  return editor;
}
export { initAssistantEditor, getAssistantEditor };
