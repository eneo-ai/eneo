import { matchesSearch } from "@/lib/search";
import type { SpaceMember } from "@/features/spaces/space";
import type { FlowSparse } from "./flows-api";

/** The states a space's flow list filters by: "Alla", "Publicerade", "Utkast". */
export const FLOW_LIST_STATUSES = ["all", "published", "drafts"] as const;
export type FlowListStatus = (typeof FLOW_LIST_STATUSES)[number];

type ListedFlow = Pick<
  FlowSparse,
  "name" | "description" | "published_version" | "updated_at" | "created_at"
>;

/** When a flow last changed in ms, by its creation if it never was; 0 when it does not say. */
export function flowChangedAt(flow: Pick<FlowSparse, "updated_at" | "created_at">): number {
  const parsed = Date.parse(flow.updated_at ?? flow.created_at ?? "");
  return Number.isNaN(parsed) ? 0 : parsed;
}

/**
 * The flows a space's list shows, as the Svelte list did (flowListRows.ts):
 * the last changed first, only those of the chosen state, and only those whose
 * name, subtitle (what the row says the flow takes in and gives back) or
 * description holds every word of the query. The description stays searchable
 * where the row does not show it.
 */
export function visibleFlows<T extends ListedFlow>(
  flows: readonly T[],
  { query, status }: { query: string; status: FlowListStatus },
  subtitle: (flow: T) => string | null
): T[] {
  return flows
    .filter(
      (flow) => status === "all" || (flow.published_version != null) === (status === "published")
    )
    .filter((flow) => matchesSearch([flow.name, subtitle(flow), flow.description], query))
    .sort((a, b) => flowChangedAt(b) - flowChangedAt(a));
}

export type FlowOwner = { kind: "you" } | { kind: "member"; name: string } | { kind: "unknown" };

/**
 * Who a flow belongs to (its owner, else whoever created it): the viewer, a
 * space member by user name or e-mail, someone the space's members do not
 * include, or nobody (null).
 */
export function flowOwner(
  flow: Pick<FlowSparse, "owner_user_id" | "created_by_user_id">,
  viewerId: string,
  members: readonly Pick<SpaceMember, "id" | "username" | "email">[]
): FlowOwner | null {
  const ownerId = flow.owner_user_id ?? flow.created_by_user_id;
  if (!ownerId) return null;
  if (ownerId === viewerId) return { kind: "you" };
  const member = members.find((candidate) => candidate.id === ownerId);
  return member ? { kind: "member", name: member.username || member.email } : { kind: "unknown" };
}
