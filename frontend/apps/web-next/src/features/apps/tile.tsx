"use client";

import { AppWindow } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { iconUrl } from "@/components/composites/icon-field";
import { ResourceTileActions, ResourceTileCard } from "@/components/composites/resource-tile";
import { Badge } from "@/components/ui/badge";
import { useSpace } from "@/features/spaces/use-space";
import { AppActions } from "./actions";
import type { AppSparse } from "./apps";

/** Grid tile for an app; clicking it opens the app's run page. */
export function AppTile({ app, showStatus }: { app: AppSparse; showStatus: boolean }) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const icon = iconUrl(app.icon_id);

  return (
    <ResourceTileCard>
      <Link
        href={`/spaces/${routeId}/apps/${app.id}`}
        className="flex flex-col items-center gap-3 pt-2 pb-1 text-center after:absolute after:inset-0 focus-visible:outline-none"
        aria-label={app.name}
      >
        <span className="bg-muted text-muted-foreground flex size-16 items-center justify-center overflow-hidden rounded-xl">
          {icon ? (
            // Backend-served upload behind the auth proxy; next/image cannot optimize it.
            // eslint-disable-next-line @next/next/no-img-element
            <img src={icon} alt="" className="size-full object-cover" />
          ) : (
            <AppWindow className="size-7" />
          )}
        </span>
        <span className="line-clamp-2 text-sm font-medium">{app.name}</span>
      </Link>
      {showStatus && (
        <div className="flex justify-center pt-2">
          <Badge variant={app.published ? "default" : "outline"}>
            {app.published ? t("published") : t("draft")}
          </Badge>
        </div>
      )}
      <ResourceTileActions>
        <AppActions app={app} />
      </ResourceTileActions>
    </ResourceTileCard>
  );
}
