import type { ChatPartner } from "@/lib/chat/types";
import type { Capability } from "@/features/capabilities/capabilities";

export type ChatCapability = {
  purpose: Capability;
  available: boolean;
  reason: string | null;
};

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
