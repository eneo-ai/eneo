import { canUseCapability } from "$lib/features/mcp/capabilities";
import type { ChatPartner } from "./ChatService.svelte";

export type ChatCapability = {
  id: string;
  purpose: string;
  name: string;
  available: boolean;
  reason: string | null;
};

type CapabilityUser = Parameters<typeof canUseCapability>[0];

/**
 * The tenant's capability providers (web search, image generation) the chat
 * partner enables, with their runtime availability. They flow through the
 * same MCP inheritance chain as other servers but are presented as
 * capabilities, not servers. A capability the user's role may not use is
 * omitted; the backend never attaches its tools for that user anyway.
 */
export function chatCapabilities(
  partner: ChatPartner | null | undefined,
  user: CapabilityUser
): ChatCapability[] {
  if (!partner) return [];
  const effective = "effective_config" in partner ? partner.effective_config : undefined;
  const purposes = effective?.mcp_enforced
    ? effective.enabled_capabilities
    : "enabled_capabilities" in partner
      ? partner.enabled_capabilities
      : [];
  const availability = effective?.mcp_enforced
    ? effective.available_capabilities
    : "available_capabilities" in partner
      ? partner.available_capabilities
      : [];
  return (purposes ?? [])
    .filter((p) => canUseCapability(user, p))
    .map((purpose) => {
      const state = availability?.find((c) => c.purpose === purpose);
      return {
        id: "capability:" + purpose,
        purpose,
        name: purpose,
        available: state?.available ?? false,
        reason: state?.reason ?? "no_active_provider"
      };
    });
}

/** Whether `purpose` is enabled for the partner, usable by the user, and has an active provider. */
export function chatCapabilityAvailable(
  partner: ChatPartner | null | undefined,
  user: CapabilityUser,
  purpose: string
): boolean {
  return chatCapabilities(partner, user).some((c) => c.purpose === purpose && c.available);
}
