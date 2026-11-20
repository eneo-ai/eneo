import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import {
  modelSupportsToolCalling,
  readinessKey,
  type Capability,
  type capabilityBlockReason
} from "@/features/capabilities/capabilities";

/**
 * Who may change what in the assistant's editor, and what its controls
 * offer: the conditions its sections apply, in one place, so the helper
 * chat's cards offer a change only where the editor's own control would
 * (decision 10).
 */

type CapabilityAvailability = Schema<"CapabilityAvailability">;

/**
 * Conversation retention: anyone who may edit the assistant in a personal
 * space; in a shared or organisation space only someone who may edit the
 * space (the backend refuses other editors).
 */
export function canEditAssistantRetention(
  space: { personal: boolean },
  canEditSpace: boolean
): boolean {
  return space.personal || canEditSpace;
}

/** The insights switch: only with the right to toggle insights. */
export function canToggleAssistantInsights(assistant: {
  permissions?: readonly string[] | null;
}): boolean {
  return (assistant.permissions ?? []).includes("insight_toggle");
}

/**
 * Knowledge and MCP servers exclude each other: the knowledge pickers are
 * disabled while the assistant has MCP servers and no knowledge. An
 * assistant that has both (older data) keeps both editable, so either can
 * be removed.
 */
export function knowledgeBlockedByMcp(knowledge: number, servers: number): boolean {
  return servers > 0 && knowledge === 0;
}

/** The other half of the rule: the MCP servers are disabled while the assistant has knowledge and no server. */
export function mcpBlockedByKnowledge(knowledge: number, servers: number): boolean {
  return knowledge > 0 && servers === 0;
}

/**
 * Whether the model the assistant answers with keeps MCP servers, their
 * tools and functions from it: a picked model without tool calling does; no
 * model picked is a separate state and does not block.
 */
export function modelBlocksTools(
  toolModel: { supports_tool_calling?: boolean | null } | null
): boolean {
  return toolModel !== null && !modelSupportsToolCalling(toolModel);
}

/**
 * Why an MCP server cannot be switched on: deactivated by an administrator,
 * or a model that cannot call tools; null when it can.
 */
export function mcpServerUnavailableReason(
  server: { is_enabled?: boolean | null },
  blocksTools: boolean
): "server_disabled" | "model_no_tool_calling" | null {
  if (server.is_enabled === false) return "server_disabled";
  return blocksTools ? "model_no_tool_calling" : null;
}

/** The document template's choice in the form (under "Skapa fil"), which also names it among the form's marks. */
export const DOCUMENT_TEMPLATE_CONTROL = "assistant-document-template";

/** A function's switch in the form, which also names its row among the form's marks. */
export const capabilityControlId = (purpose: string) => `assistant-${purpose}`;

/**
 * A function's own line in the form (its name, its hint and its switch),
 * where a reference to the function lands; "Skapa fil"'s template choice
 * under it has a reference of its own.
 */
export const capabilityRowId = (purpose: string) => `assistant-capability-${purpose}`;

/**
 * Where a function's readiness is read: the policy's under a policy that
 * governs the functions, else the assistant's, else the space's.
 */
export function capabilityAvailability(
  assistant: {
    available_capabilities?: CapabilityAvailability[];
    effective_config?: {
      mcp_enforced?: boolean;
      available_capabilities?: CapabilityAvailability[];
    } | null;
  },
  space: { available_capabilities?: CapabilityAvailability[] },
  purpose: Capability
): CapabilityAvailability | undefined {
  const governed = assistant.effective_config?.mcp_enforced === true;
  return (
    governed
      ? assistant.effective_config?.available_capabilities
      : (assistant.available_capabilities ?? space.available_capabilities)
  )?.find((item) => item.purpose === purpose);
}

/**
 * The message key that says why a function cannot be switched on
 * (`capabilityBlockReason`), with the provider's own reason where it has one.
 */
export function capabilityBlockMessageKey(
  blocked: NonNullable<ReturnType<typeof capabilityBlockReason>>,
  availability: CapabilityAvailability | undefined
): string {
  return readinessKey(
    blocked === "no_active_provider" ? (availability?.reason ?? blocked) : blocked
  );
}

type SpaceModels = Schema<"ModelsPresentation">;

/** The models the space offers, as the result ranking reads them. */
export function spaceModelsQueryOptions(api: EneoClient, spaceId: string) {
  return queryOptions({
    queryKey: ["ai-models", spaceId],
    queryFn: (): Promise<SpaceModels> =>
      unwrap(api.GET("/api/v1/ai-models/", { params: { query: { space_id: spaceId } } }))
  });
}

/** The ranking models the space lets the assistant choose (the backend refuses others). */
export function selectableRerankModels(models: SpaceModels | undefined) {
  return (models?.rerank_models ?? []).filter(
    (model) => model.can_access && model.meets_security_classification !== false
  );
}

/**
 * Whether the result ranking row is shown: where the space has a model to
 * choose, or a model is chosen (one no longer allowed stays visible until
 * it is changed).
 */
export function rerankerShown(
  selectable: readonly unknown[],
  ...chosen: (string | null | undefined)[]
): boolean {
  return selectable.length > 0 || chosen.some((id) => id != null);
}
