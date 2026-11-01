"use client";

import { useSuspenseQuery } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { BackLink } from "@/components/composites/back-link";
import { PageHeader } from "@/components/composites/page-header";
import { browserApi } from "@/lib/api/browser";
import { AppRunTabs } from "@/features/apps/app-run-tabs";
import { appQueryOptions } from "@/features/apps/apps";

/** Dashboard consumer view of an app: run it and browse its results. */
export function DashboardApp({ appId }: { appId: string }) {
  const t = useTranslations();
  const { data: app } = useSuspenseQuery(appQueryOptions(browserApi, appId));

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div className="flex flex-col gap-1">
        <BackLink href="/dashboard">{t("assistants")}</BackLink>
        <PageHeader title={app.name} />
      </div>

      <AppRunTabs app={app} base={`/dashboard/app/${appId}`} />
    </div>
  );
}
