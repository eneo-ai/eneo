import type { Capability } from "@/features/capabilities/capabilities";

export type ChatCapability = {
  purpose: Capability;
  available: boolean;
  reason: string | null;
};

/** The ask endpoint accepts capability purpose names, independently of MCP server IDs. */
export function disabledCapabilitiesForRequest(
  disabled: Set<Capability>
): Capability[] | undefined {
  return disabled.size > 0 ? [...disabled] : undefined;
}
