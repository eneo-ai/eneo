"use client";

import { useTranslations } from "next-intl";
import { EntityAvatar } from "@/components/composites/entity-avatar";
import { iconUrl } from "@/components/composites/icon-field";
import { ResourceCard } from "@/components/composites/resource-tile";
import { StatusLabel } from "@/components/composites/status-label";
import { useSpace } from "@/features/spaces/use-space";
import { AppActions } from "./actions";
import type { AppSparse } from "./apps";

/** Card for an app; the card opens the app's run page. */
export function AppTile({ app, showStatus }: { app: AppSparse; showStatus: boolean }) {
  const t = useTranslations();
  const { routeId } = useSpace();

  return (
    <ResourceCard
      href={`/spaces/${routeId}/apps/${app.id}`}
      name={app.name}
      tile={
        <EntityAvatar
          name={app.name}
          id={app.id}
          src={iconUrl(app.icon_id)}
          size="lg"
          className="size-9"
        />
      }
      status={
        showStatus ? (
          <StatusLabel
            status={app.published ? "success" : "neutral"}
            label={app.published ? t("published") : t("draft")}
            className="text-xs font-semibold"
          />
        ) : null
      }
      description={app.description}
      actions={<AppActions app={app} />}
    />
  );
}
