import { matchesSearch } from "@/lib/search";
import type { SpaceMember } from "@/features/spaces/space";
import type { FlowSparse } from "./flows-api";

type ListedFlow = Pick<FlowSparse, "name" | "description">;

/** When a flow last changed in ms, by its creation if it never was; 0 when it does not say. */
export function flowChangedAt(flow: Pick<FlowSparse, "updated_at" | "created_at">): number {
  const parsed = Date.parse(flow.updated_at ?? flow.created_at ?? "");
  return Number.isNaN(parsed) ? 0 : parsed;
}

/**
 * The flows whose name, subtitle (what the row says the flow takes in and
 * gives back) or description holds every word of the query, in the order
 * given. The description stays searchable where a row does not show it.
 */
export function matchingFlows<T extends ListedFlow>(
  flows: readonly T[],
  query: string,
  subtitle: (flow: T) => string | null
): T[] {
  return flows.filter((flow) =>
    matchesSearch([flow.name, subtitle(flow), flow.description], query)
  );
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
