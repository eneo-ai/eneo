import type { Schema } from "@/lib/api/models";
import type { Space, SpaceRouteId } from "@/features/spaces/space";

export type AssistantSparse = Schema<"AssistantSparse">;
export type GroupChatSparse = Schema<"GroupChatSparse">;

/** One row/tile on the assistants page: an assistant or a group chat. */
export type ChatAppItem = AssistantSparse | GroupChatSparse;

/** Assistants and group chats merged and name-sorted, like the Svelte SpacesManager. */
export function spaceChatItems(space: Space): ChatAppItem[] {
  return [
    ...(space.applications?.assistants.items ?? []),
    ...(space.applications?.group_chats.items ?? [])
  ].sort((a, b) => a.name.localeCompare(b.name));
}

export function chatPartnerHref(
  routeId: SpaceRouteId,
  item: Pick<ChatAppItem, "type" | "id">
): string {
  const params = new URLSearchParams({ type: item.type, id: item.id });
  return `/spaces/${routeId}/chat?${params}`;
}

/** Icon uploads are served through the auth-injecting proxy. */
export function iconUrl(iconId: string | null | undefined): string | null {
  return iconId ? `/api/eneo/api/v1/icons/${iconId}/` : null;
}
