"use client";

import { useSuspenseQuery } from "@tanstack/react-query";
import { replaceUrl, useSearchParams } from "@/lib/navigation";
import { useTranslations } from "use-intl";
import { BackLink } from "@/components/composites/back-link";
import { PageHeader } from "@/components/composites/page-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { browserApi } from "@/lib/api/browser";
import { appQueryOptions, readAppTab } from "@/features/apps/apps";
import { ResultsTable } from "@/features/apps/results/results-table";
import { RunView } from "@/features/apps/run/run-view";

/** Dashboard consumer view of an app: run it and browse its results. */
export function DashboardApp({ appId }: { appId: string }) {
  const t = useTranslations();
  const searchParams = useSearchParams();
  const { data: app } = useSuspenseQuery(appQueryOptions(browserApi, appId));

  const base = `/dashboard/app/${appId}`;
  const resultHref = (runId: string) => `${base}/results/${runId}`;

  const tab = readAppTab(searchParams);

  function selectTab(next: string) {
    const url = new URL(window.location.href);
    url.searchParams.set("tab", next);
    replaceUrl(url);
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div className="flex flex-col gap-1">
        <BackLink href="/dashboard">{t("dashboard")}</BackLink>
        <PageHeader title={app.name} />
      </div>

      <Tabs value={tab} onValueChange={selectTab}>
        <TabsList>
          <TabsTrigger value="run">{t("run")}</TabsTrigger>
          <TabsTrigger value="results">{t("results")}</TabsTrigger>
        </TabsList>
        {/* Kept mounted: a peek at Resultat must not throw away the typed text and delete the uploaded files. */}
        <TabsContent value="run" forceMount className="pt-4 data-[state=inactive]:hidden">
          <RunView app={app} resultHref={resultHref} />
        </TabsContent>
        <TabsContent value="results" className="pt-4">
          <ResultsTable appId={appId} resultHref={resultHref} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
