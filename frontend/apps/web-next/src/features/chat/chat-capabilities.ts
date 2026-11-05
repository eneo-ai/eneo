import type { ChatPartner } from "@/lib/chat/types";
import type { Capability } from "@/features/capabilities/capabilities";

export type ChatCapability = {
  purpose: Capability;
  available: boolean;
  reason: string | null;
};

/**
 * The capabilities (web search, image generation, ...) the partner enables,
 * as the Svelte app's chatCapabilities: effective governance replaces the
 * assistant's own list, a capability the user's role may not use is omitted,
 * and one without an active provider is unavailable, with the reason.
 */
export function chatCapabilities(
  partner: ChatPartner,
  canUse: (purpose: Capability) => boolean
): ChatCapability[] {
  const effective = partner.effectiveConfig;
  const purposes = effective?.mcp_enforced
    ? effective.enabled_capabilities
    : partner.enabledCapabilities;
  const availability = effective?.mcp_enforced
    ? effective.available_capabilities
    : partner.availableCapabilities;
  return (purposes ?? []).filter(canUse).map((purpose) => {
    const status = availability?.find((item) => item.purpose === purpose);
    return {
      purpose,
      available: status?.available ?? false,
      reason: status ? (status.reason ?? null) : "no_active_provider"
    };
  });
}

/** The capability as the composer shows it when the model cannot call tools. */
export function withoutToolCalling(capability: ChatCapability): ChatCapability {
  return capability.available
    ? { ...capability, available: false, reason: "model_no_tool_calling" }
    : capability;
}

export function defaultDisabledCapabilities(partner: ChatPartner): Capability[] {
  return partner.effectiveConfig?.default_disabled_capabilities ?? [];
}

/** The ask endpoint accepts capability purpose names, independently of MCP server IDs. */
export function disabledCapabilitiesForRequest(
  disabled: Set<Capability>
): Capability[] | undefined {
  return disabled.size > 0 ? [...disabled] : undefined;
}
