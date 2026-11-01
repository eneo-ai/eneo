"use client";

import { Button } from "@astryxdesign/core/Button";
import { Pencil } from "lucide-react";
import { useSuspenseQuery } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { BackLink } from "@/components/composites/back-link";
import { PageHeader } from "@/components/composites/page-header";
import { browserApi } from "@/lib/api/browser";
import { useSpace } from "@/features/spaces/use-space";
import { PHONE_QUERY, useMediaMatch } from "@/lib/hooks/use-media-match";
import { AppRunTabs } from "./app-run-tabs";
import { appQueryOptions } from "./apps";

/** App run/results surface, with the active tab tracked in ?tab=. */
export function AppDetail({ appId }: { appId: string }) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const phone = useMediaMatch(PHONE_QUERY);
  const { data: app } = useSuspenseQuery(appQueryOptions(browserApi, appId));

  const base = `/spaces/${routeId}/apps/${appId}`;
  const canEdit = (app.permissions ?? []).includes("edit");

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div className="flex flex-col gap-1">
        <BackLink href={`/spaces/${routeId}/apps`} hideOnPhone>
          {t("apps")}
        </BackLink>
        <PageHeader
          title={app.name}
          actions={
            canEdit && (
              // A phone has room for the name and a pencil, not a button of its own under it.
              <Button
                href={`${base}/edit`}
                label={t("edit")}
                tooltip={phone ? t("edit") : undefined}
                isIconOnly={phone}
                icon={phone ? <Pencil aria-hidden="true" /> : undefined}
                variant={phone ? "ghost" : undefined}
              />
            )
          }
        />
      </div>

      <AppRunTabs app={app} base={base} />
    </div>
  );
}
