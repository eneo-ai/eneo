import type { ChatPartner } from "@/lib/chat/types";
import type { Capability } from "@/features/capabilities/capabilities";

export type ChatCapability = {
  purpose: Capability;
  available: boolean;
  reason: string | null;
};

/** Effective governance replaces the assistant's own capability list. */
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

export function defaultDisabledCapabilities(partner: ChatPartner): Capability[] {
  return partner.effectiveConfig?.default_disabled_capabilities ?? [];
}

/** The ask endpoint accepts capability purpose names, independently of MCP server IDs. */
export function disabledCapabilitiesForRequest(
  partner: ChatPartner,
  disabled: Set<Capability>,
  showWebSearch: boolean
): Capability[] | undefined {
  const purposes = new Set(disabled);
  if (partner.type === "default-assistant" && !showWebSearch) purposes.add("web_search");
  return purposes.size > 0 ? [...purposes] : undefined;
}
