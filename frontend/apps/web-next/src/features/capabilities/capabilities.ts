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
}): "space_disabled" | "model_unsupported" | "no_active_provider" | null {
  if (enabled) return null;
  if (!spaceEnabled) return "space_disabled";
  if (!modelSupportsTools) return "model_unsupported";
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
  model_unsupported: "model_does_not_support_tools"
};

export function readinessKey(reason: string | null | undefined) {
  return READINESS_KEYS[reason ?? ""] ?? "tools_readiness_unknown";
}
