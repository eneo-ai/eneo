"use client";

import { useSuspenseQuery } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { PageHeader } from "@/components/composites/page-header";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/api/browser";
import { useSpace } from "@/features/spaces/use-space";
import { appQueryOptions } from "../apps";
import { AiSection } from "./ai-section";
import { GeneralSection } from "./general-section";
import { InputSection } from "./input-section";
import { InstructionsSection } from "./instructions-section";
import { PublishingSection } from "./publishing-section";
import { SecuritySection } from "./security-section";

/**
 * App settings, saved per section (web-next pattern). Prompt history,
 * attachments and API-keys sections are deferred, like the assistant editor.
 */
export function AppEditor({ appId }: { appId: string }) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const { data: app } = useSuspenseQuery(appQueryOptions(browserApi, appId));

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
      <div className="flex flex-col gap-1">
        <Link
          href={`/spaces/${routeId}/apps/${app.id}`}
          className="text-muted-foreground hover:text-foreground flex w-fit items-center gap-1 text-sm"
        >
          <ChevronLeft className="size-4" />
          {app.name}
        </Link>
        <PageHeader title={t("edit")}>
          <Button asChild variant="outline">
            <Link href={`/spaces/${routeId}/apps/${app.id}`}>{t("done")}</Link>
          </Button>
        </PageHeader>
      </div>
      <GeneralSection app={app} />
      <InputSection app={app} />
      <InstructionsSection app={app} />
      <AiSection app={app} />
      <SecuritySection app={app} />
      <PublishingSection app={app} />
      <div className="min-h-12" />
    </div>
  );
}
