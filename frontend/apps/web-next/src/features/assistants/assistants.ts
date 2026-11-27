import type { Schema } from "@/lib/api/models";
import type { Space, SpaceRouteId } from "@/features/spaces/space";

export type AssistantSparse = Schema<"AssistantSparse">;
export type GroupChatSparse = Schema<"GroupChatSparse">;

/** One row/tile on the assistants page: an assistant or a group chat. */
export type ChatAppItem = AssistantSparse | GroupChatSparse;

/**
 * The chat's partner switcher does not pass a collator yet; Swedish is the
 * app's default locale, and a fixed locale sorts the same on server and client.
 */
const swedishCompare = new Intl.Collator("sv").compare;

/**
 * Assistants and group chats merged and name-sorted, like the Svelte
 * SpacesManager. Pass the locale's collator (Astryx `useCollator().compare`)
 * so å, ä and ö sort the same on the server and in the browser.
 */
export function spaceChatItems(
  space: Space,
  compare: Intl.Collator["compare"] = swedishCompare
): ChatAppItem[] {
  return [
    ...(space.applications?.assistants.items ?? []),
    ...(space.applications?.group_chats.items ?? [])
  ].sort((a, b) => compare(a.name, b.name));
}

export function chatPartnerHref(
  routeId: SpaceRouteId,
  item: Pick<ChatAppItem, "type" | "id">
): string {
  const params = new URLSearchParams({ type: item.type, id: item.id });
  return `/spaces/${routeId}/chat?${params}`;
}
