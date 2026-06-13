"use client";

import { useSuspenseQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { PageHeader } from "@/components/composites/page-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { browserApi } from "@/lib/api/browser";
import { securityClassificationsQueryOptions } from "@/features/admin/security-classifications/security-classifications";
import { ModelTable } from "./model-table";
import { adminModelsQueryOptions } from "./models";

/**
 * Admin model management: completion / embedding / transcription tabs grouped
 * by provider, with enable/disable, set-default and security-classification
 * assignment. The add-model wizard, provider/credential management, usage
 * breakdowns and the migration flow are deferred (tracked in the ledger).
 */
export function ModelsPage() {
  const t = useTranslations();
  const { data: models } = useSuspenseQuery(adminModelsQueryOptions(browserApi));
  const { data: security } = useSuspenseQuery(securityClassificationsQueryOptions(browserApi));

  const securityEnabled = security.security_enabled;
  const classifications = security.security_classifications;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader title={t("models")} />
      <Tabs defaultValue="completion">
        <TabsList>
          <TabsTrigger value="completion">{t("completion_models")}</TabsTrigger>
          <TabsTrigger value="embedding">{t("embedding_models")}</TabsTrigger>
          <TabsTrigger value="transcription">{t("transcription_models")}</TabsTrigger>
        </TabsList>
        <TabsContent value="completion" className="pt-4">
          <ModelTable
            models={models.completion_models}
            kind="completion"
            classifications={classifications}
            securityEnabled={securityEnabled}
          />
        </TabsContent>
        <TabsContent value="embedding" className="pt-4">
          <ModelTable
            models={models.embedding_models}
            kind="embedding"
            classifications={classifications}
            securityEnabled={securityEnabled}
          />
        </TabsContent>
        <TabsContent value="transcription" className="pt-4">
          <ModelTable
            models={models.transcription_models}
            kind="transcription"
            classifications={classifications}
            securityEnabled={securityEnabled}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
