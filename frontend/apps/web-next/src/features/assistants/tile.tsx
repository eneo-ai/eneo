"use client";

import { Bot, Users } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { iconUrl } from "@/components/composites/icon-field";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { entityAccent } from "@/lib/entity-accent";
import { cn } from "@/lib/utils";
import { useSpace } from "@/features/spaces/use-space";
import { ChatAppActions } from "./actions";
import { chatPartnerHref, type ChatAppItem } from "./assistants";

/**
 * Grid tile for an assistant or group chat; clicking it opens the chat. The
 * fallback icon is tinted with a deterministic per-id accent (entityAccent) so
 * the grid has visual identity instead of a wall of identical grey squares.
 */
export function ChatAppTile({ item, showStatus }: { item: ChatAppItem; showStatus: boolean }) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const icon = iconUrl(item.icon_id);

  return (
    <Card className="group hover:border-primary/40 focus-within:border-ring focus-within:ring-ring/50 relative gap-0 p-4 transition-colors focus-within:ring-[3px]">
      <Link
        href={chatPartnerHref(routeId, item)}
        className="flex flex-col items-center gap-3 pt-2 pb-1 text-center after:absolute after:inset-0 focus-visible:outline-none"
        aria-label={item.name}
      >
        <span
          className={cn(
            "flex size-16 items-center justify-center overflow-hidden rounded-xl",
            entityAccent(item.id)
          )}
        >
          {icon ? (
            // Backend-served upload behind the auth proxy; next/image cannot optimize it.
            // eslint-disable-next-line @next/next/no-img-element
            <img src={icon} alt="" className="size-full object-cover" />
          ) : item.type === "group-chat" ? (
            <Users className="size-7" />
          ) : (
            <Bot className="size-7" />
          )}
        </span>
        <span className="line-clamp-2 text-sm font-medium">{item.name}</span>
      </Link>
      {showStatus && (
        <div className="flex justify-center pt-2">
          <Badge variant={item.published ? "default" : "outline"}>
            {item.published ? t("published") : t("draft")}
          </Badge>
        </div>
      )}
      <div className="absolute top-2 right-2 z-10 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
        <ChatAppActions item={item} />
      </div>
    </Card>
  );
}
