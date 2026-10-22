"use client";

import { useTranslations } from "next-intl";
import { EntityAvatar } from "@/components/composites/entity-avatar";
import { iconUrl } from "@/components/composites/icon-field";
import { ResourceCard } from "@/components/composites/resource-tile";
import { StatusLabel } from "@/components/composites/status-label";
import { assistantModelName } from "@/features/spaces/space-models";
import { useSpace } from "@/features/spaces/use-space";
import { ChatAppActions } from "./actions";
import { chatPartnerHref, type ChatAppItem } from "./assistants";

/**
 * Card for an assistant; the card opens the chat. The tile is the uploaded
 * icon or coloured initials, the tokens name the chat model when the space
 * still offers it.
 */
export function ChatAppTile({
  item,
  showStatus,
  showActions = true
}: {
  item: ChatAppItem;
  showStatus: boolean;
  /** The overview shows cards without the actions menu. */
  showActions?: boolean;
}) {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const model = assistantModelName(space, item);

  return (
    <ResourceCard
      href={chatPartnerHref(routeId, item)}
      name={item.name}
      tile={
        <EntityAvatar
          name={item.name}
          id={item.id}
          src={iconUrl(item.icon_id)}
          size="lg"
          className="size-9 [&_svg]:size-4.5"
        />
      }
      status={
        showStatus ? (
          <StatusLabel
            status={item.published ? "success" : "neutral"}
            label={item.published ? t("published") : t("draft")}
            className="text-xs font-semibold"
          />
        ) : null
      }
      description={item.description}
      meta={model ? [model] : []}
      actions={showActions ? <ChatAppActions item={item} /> : null}
    />
  );
}
