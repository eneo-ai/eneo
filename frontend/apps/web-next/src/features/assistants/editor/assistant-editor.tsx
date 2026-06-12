"use client";

import { useSuspenseQuery } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { PageHeader } from "@/components/composites/page-header";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/api/browser";
import { useSpace } from "@/features/spaces/use-space";
import { chatPartnerHref } from "../assistants";
import { AiSection } from "./ai-section";
import { GeneralSection } from "./general-section";
import { InstructionsSection } from "./instructions-section";
import { PublishingSection } from "./publishing-section";
import { SecuritySection } from "./security-section";
import { assistantQueryOptions } from "./use-assistant";

/**
 * Assistant settings, saved per section (web-next pattern; the Svelte app's
 * global draft/diff editor is intentionally not ported). Knowledge, MCP
 * servers, attachments and prompt history are tracked as deferred in the
 * migration ledger.
 */
export function AssistantEditor({ assistantId }: { assistantId: string }) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const { data: assistant } = useSuspenseQuery(assistantQueryOptions(browserApi, assistantId));

  const chatHref = chatPartnerHref(routeId, { ...assistant, type: "assistant" as const });

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
      <div className="flex flex-col gap-1">
        <Link
          href={`/spaces/${routeId}/assistants`}
          className="text-muted-foreground hover:text-foreground flex w-fit items-center gap-1 text-sm"
        >
          <ChevronLeft className="size-4" />
          {t("assistants")}
        </Link>
        <PageHeader title={assistant.name}>
          <Button asChild variant="outline">
            <Link href={chatHref}>{t("done")}</Link>
          </Button>
        </PageHeader>
      </div>
      <GeneralSection assistant={assistant} />
      <InstructionsSection assistant={assistant} />
      <AiSection assistant={assistant} />
      <SecuritySection assistant={assistant} />
      <PublishingSection assistant={assistant} />
      <div className="min-h-12" />
    </div>
  );
}
