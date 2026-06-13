"use client";

import { useTranslations } from "next-intl";
import { EmptyState } from "@/components/composites/empty-state";
import { PageHeader } from "@/components/composites/page-header";
import { useSpace } from "@/features/spaces/use-space";
import { spaceApps, type AppSparse } from "./apps";
import { CreateAppButton } from "./create-app";
import { AppTile } from "./tile";

function TileGrid({ items, showStatus }: { items: AppSparse[]; showStatus: boolean }) {
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
      {items.map((app) => (
        <AppTile key={app.id} app={app} showStatus={showStatus} />
      ))}
    </div>
  );
}

/** Apps in one grid, grouped into published/drafts for users who can publish. */
export function AppsPage() {
  const t = useTranslations();
  const { space, can } = useSpace();

  const items = spaceApps(space);
  const showStatus = !space.personal;
  const groupByStatus = can("publish", "app");
  const published = items.filter((app) => app.published);
  const drafts = items.filter((app) => !app.published);

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader title={t("apps")}>{can("create", "app") && <CreateAppButton />}</PageHeader>
      {items.length === 0 ? (
        <EmptyState title={t("there_are_currently_no_apps_configured")} />
      ) : groupByStatus ? (
        <div className="flex flex-col gap-6">
          {published.length > 0 && (
            <section className="flex flex-col gap-2">
              <h2 className="text-muted-foreground text-sm font-medium">{t("published")}</h2>
              <TileGrid items={published} showStatus={false} />
            </section>
          )}
          {drafts.length > 0 && (
            <section className="flex flex-col gap-2">
              <h2 className="text-muted-foreground text-sm font-medium">{t("drafts")}</h2>
              <TileGrid items={drafts} showStatus={false} />
            </section>
          )}
        </div>
      ) : (
        <TileGrid items={items} showStatus={showStatus} />
      )}
    </div>
  );
}
