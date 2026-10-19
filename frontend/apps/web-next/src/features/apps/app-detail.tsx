"use client";

import { useSuspenseQuery } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { PageHeader } from "@/components/composites/page-header";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { browserApi } from "@/lib/api/browser";
import { useSpace } from "@/features/spaces/use-space";
import { appQueryOptions } from "./apps";
import { ResultsTable } from "./results/results-table";
import { RunView } from "./run/run-view";

/** App run/results surface, with the active tab tracked in ?tab=. */
export function AppDetail({ appId }: { appId: string }) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const searchParams = useSearchParams();
  const { data: app } = useSuspenseQuery(appQueryOptions(browserApi, appId));

  const base = `/spaces/${routeId}/apps/${appId}`;
  const resultHref = (runId: string) => `${base}/results/${runId}`;

  const requested = searchParams.get("tab");
  const [tab, setTab] = useState(requested === "results" ? "results" : "run");

  function selectTab(next: string) {
    setTab(next);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", next);
    window.history.replaceState(null, "", url);
  }

  const canEdit = (app.permissions ?? []).includes("edit");

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div className="flex flex-col gap-1">
        <Link
          href={`/spaces/${routeId}/apps`}
          className="text-muted-foreground hover:text-foreground flex w-fit items-center gap-1 text-sm"
        >
          <ChevronLeft className="size-4" />
          {t("apps")}
        </Link>
        <PageHeader title={app.name}>
          {canEdit && (
            <Button asChild variant="outline">
              <Link href={`${base}/edit`}>{t("edit")}</Link>
            </Button>
          )}
        </PageHeader>
      </div>

      <Tabs value={tab} onValueChange={selectTab}>
        <TabsList>
          <TabsTrigger value="run">{t("run")}</TabsTrigger>
          <TabsTrigger value="results">{t("results")}</TabsTrigger>
        </TabsList>
        <TabsContent value="run" className="pt-4">
          <RunView app={app} resultHref={resultHref} />
        </TabsContent>
        <TabsContent value="results" className="pt-4">
          <ResultsTable appId={appId} resultHref={resultHref} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
