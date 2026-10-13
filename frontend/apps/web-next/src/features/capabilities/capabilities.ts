import { Globe, Image } from "lucide-react";
import type { Schema } from "@/lib/api/models";

export type Capability = Schema<"CapabilityAvailability">["purpose"];

/** One display and readiness owner for the two tenant functions. */
export const CAPABILITIES = [
  {
    purpose: "web_search",
    icon: Globe,
    spaceHint: "web_search_space_group_hint",
    assistantHint: "web_search_capability_hint"
  },
  {
    purpose: "image_generation",
    icon: Image,
    spaceHint: "image_generation_space_group_hint",
    assistantHint: "image_generation_capability_hint"
  }
] as const;

export function toggleCapability(selected: Capability[], purpose: Capability): Capability[] {
  return selected.includes(purpose)
    ? selected.filter((item) => item !== purpose)
    : [...selected, purpose];
}

/**
 * Whether the completion model can call tools at all. Mirrors the backend
 * gate (`if not model.supports_tool_calling`): only an explicit `true` lets
 * MCP servers, capabilities and loopback tools reach the model, so a missing
 * flag counts as no support rather than as unknown.
 */
export function modelSupportsToolCalling(
  model: { supports_tool_calling?: boolean | null } | null | undefined
): boolean {
  return model?.supports_tool_calling === true;
}

export function capabilityBlockReason({
  enabled,
  spaceEnabled,
  available,
  modelSupportsTools
}: {
  enabled: boolean;
  spaceEnabled: boolean;
  available: boolean;
  modelSupportsTools: boolean;
}): "space_disabled" | "model_no_tool_calling" | "no_active_provider" | null {
  if (enabled) return null;
  if (!spaceEnabled) return "space_disabled";
  if (!modelSupportsTools) return "model_no_tool_calling";
  if (!available) return "no_active_provider";
  return null;
}

export const READINESS_KEYS: Record<string, string> = {
  permission: "tools_readiness_permission",
  space_disabled: "tools_readiness_space_disabled",
  server_disabled: "tools_readiness_server_disabled",
  model_missing: "tools_readiness_model_missing",
  model_disabled: "tools_readiness_model_disabled",
  model_deprecated: "tools_readiness_model_deprecated",
  model_provider_inactive: "tools_readiness_model_provider_inactive",
  no_approved_tools: "tools_readiness_no_approved_tools",
  classification: "tools_readiness_classification",
  no_active_provider: "tools_readiness_no_active_provider",
  model_no_tool_calling: "tools_readiness_model_no_tool_calling"
};

export function readinessKey(reason: string | null | undefined) {
  return READINESS_KEYS[reason ?? ""] ?? "tools_readiness_unknown";
}
