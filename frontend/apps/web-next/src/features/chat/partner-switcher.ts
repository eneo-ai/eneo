import {
  chatPartnerHref,
  spaceChatItems,
  type ChatAppItem
} from "@/features/assistants/assistants";
import type { Space, SpaceRouteId } from "@/features/spaces/space";

export type ChatPartnerSwitcherItem = {
  id: string;
  type: ChatAppItem["type"] | "default-assistant";
  name: string;
  href: string;
  iconId?: string | null;
  active: boolean;
};

export function chatPartnerSwitcherItems({
  space,
  routeId,
  activeType,
  activeId
}: {
  space: Space;
  routeId: SpaceRouteId;
  activeType: ChatPartnerSwitcherItem["type"];
  activeId: string;
}): ChatPartnerSwitcherItem[] {
  const defaultAssistant = space.default_assistant
    ? [
        {
          id: space.default_assistant.id,
          type: "default-assistant" as const,
          name: space.default_assistant.name,
          href: `/spaces/${routeId}/chat`,
          iconId: space.default_assistant.icon_id,
          active: activeType === "default-assistant" || activeId === space.default_assistant.id
        }
      ]
    : [];

  return [
    ...defaultAssistant,
    ...spaceChatItems(space).map((item) => ({
      id: item.id,
      type: item.type,
      name: item.name,
      href: chatPartnerHref(routeId, item),
      iconId: item.icon_id,
      active: activeType === item.type && activeId === item.id
    }))
  ];
}
