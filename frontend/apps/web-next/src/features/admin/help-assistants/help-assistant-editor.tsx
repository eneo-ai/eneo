"use client";

import { useSuspenseQuery } from "@tanstack/react-query";
import { ChevronLeft, Info } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { PageHeader } from "@/components/composites/page-header";
import { SaveStatusIndicator, SaveStatusProvider } from "@/components/composites/save-status";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/api/browser";
import { AiSection } from "@/features/assistants/editor/ai-section";
import { GeneralSection } from "@/features/assistants/editor/general-section";
import { InstructionsSection } from "@/features/assistants/editor/instructions-section";
import { SecuritySection } from "@/features/assistants/editor/security-section";
import { assistantQueryOptions } from "@/features/assistants/editor/use-assistant";
import { PROMPT_GUIDE_KIND } from "@/features/help-assistants/prompt-guide/helper-runs";
import type { HelperKind } from "./help-assistants";

/**
 * Help-assistant settings. A help assistant is a regular assistant edited via
 * the standard assistant endpoints, so the assistant-editor sections are reused
 * verbatim; only the general/prompt/model/retention subset applies. Hosted under
 * a SpaceProvider routeId="organization" so the reused sections resolve the
 * org-space model list + retention inheritance.
 */
export function HelpAssistantEditor({
  assistantId,
  helperKind
}: {
  assistantId: string;
  helperKind: HelperKind;
}) {
  const t = useTranslations();
  const { data: assistant } = useSuspenseQuery(assistantQueryOptions(browserApi, assistantId));

  return (
    <SaveStatusProvider>
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
        <div className="flex flex-col gap-1">
          <Link
            href="/admin/help-assistants"
            className="text-muted-foreground hover:text-foreground flex w-fit items-center gap-1 text-sm"
          >
            <ChevronLeft className="size-4" />
            {t("admin_help_assistants_nav_label")}
          </Link>
          <PageHeader title={assistant.name}>
            <SaveStatusIndicator />
            <Button asChild variant="outline">
              <Link href="/admin/help-assistants">{t("done")}</Link>
            </Button>
          </PageHeader>
        </div>

        <p className="bg-accent text-accent-foreground rounded-lg border px-4 py-3 text-sm">
          {t("admin_help_assistants_edit_banner")}
        </p>

        <GeneralSection assistant={assistant} />

        <p className="border-warning/30 bg-warning/10 text-warning rounded-md border px-3 py-2 text-sm">
          {t("admin_help_assistants_edit_prompt_warning")}
        </p>
        <InstructionsSection assistant={assistant} promptGuide={helperKind !== PROMPT_GUIDE_KIND} />

        <AiSection assistant={assistant} />

        <p className="border-border bg-card text-muted-foreground flex items-start gap-2.5 rounded-lg border px-3 py-2.5 text-sm">
          <Info className="mt-0.5 size-4 shrink-0" />
          {t("admin_help_assistants_edit_logging_explanation")}
        </p>
        <SecuritySection assistant={assistant} />

        <div className="min-h-12" />
      </div>
    </SaveStatusProvider>
  );
}
