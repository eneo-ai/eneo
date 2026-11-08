import type { Schema } from "@/lib/api/models";
import type { Space, SpaceRouteId } from "@/features/spaces/space";

export type AssistantSparse = Schema<"AssistantSparse">;

/** One row/tile on the assistants page. */
export type ChatAppItem = AssistantSparse;

/**
 * The chat's partner switcher does not pass a collator yet; Swedish is the
 * app's default locale, and a fixed locale sorts the same on server and client.
 */
const swedishCompare = new Intl.Collator("sv").compare;

/**
 * The space's assistants name-sorted, like the Svelte SpacesManager. Pass the
 * locale's collator (Astryx `useCollator().compare`) so å, ä and ö sort the
 * same on the server and in the browser.
 */
export function spaceChatItems(
  space: Space,
  compare: Intl.Collator["compare"] = swedishCompare
): ChatAppItem[] {
  return [...(space.applications?.assistants.items ?? [])].sort((a, b) => compare(a.name, b.name));
}

export function chatPartnerHref(
  routeId: SpaceRouteId,
  item: Pick<ChatAppItem, "type" | "id">
): string {
  const params = new URLSearchParams({ type: item.type, id: item.id });
  return `/spaces/${routeId}/chat?${params}`;
}
