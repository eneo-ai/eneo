"use client";

import { useSuspenseQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { PageHeader } from "@/components/composites/page-header";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { browserApi } from "@/lib/api/browser";
import { securityClassificationsQueryOptions } from "@/features/admin/security-classifications/security-classifications";
import { AddModelWizard } from "./add-model-wizard";
import { CredentialsPanel } from "./credentials-panel";
import { ModelTable } from "./model-table";
import { adminModelsQueryOptions } from "./models";

/**
 * Admin model management: completion / embedding / transcription tabs grouped
 * by provider (enable/disable, set-default, security classification, full edit
 * of custom models) plus per-provider API credentials. The add-model wizard,
 * usage breakdowns and the migration flow are deferred (tracked in the ledger).
 */
export function ModelsPage() {
  const t = useTranslations();
  const { data: models } = useSuspenseQuery(adminModelsQueryOptions(browserApi));
  const { data: security } = useSuspenseQuery(securityClassificationsQueryOptions(browserApi));

  const securityEnabled = security.security_enabled;
  const classifications = security.security_classifications;
  const [showAdd, setShowAdd] = useState(false);

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader title={t("models")}>
        <Button onClick={() => setShowAdd(true)}>
          <Plus className="size-4" /> {t("add_model")}
        </Button>
      </PageHeader>
      <AddModelWizard open={showAdd} onOpenChange={setShowAdd} />
      <Tabs defaultValue="completion">
        <TabsList>
          <TabsTrigger value="completion">{t("completion_models")}</TabsTrigger>
          <TabsTrigger value="embedding">{t("embedding_models")}</TabsTrigger>
          <TabsTrigger value="transcription">{t("transcription_models")}</TabsTrigger>
          <TabsTrigger value="credentials">{t("api_credentials")}</TabsTrigger>
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
        <TabsContent value="credentials" className="pt-4">
          <CredentialsPanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}
