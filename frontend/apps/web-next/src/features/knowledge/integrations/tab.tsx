"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { Button } from "@/components/ui/button";
import { useSpace } from "@/features/spaces/use-space";
import { embeddingModelsInUse } from "../knowledge";
import { groupIntegrationRows } from "./grouping";
import { ImportKnowledgeDialog, useImportableIntegrations } from "./import/import-dialog";
import { IntegrationItemsTable } from "./table";

function ImportToolbar() {
  const t = useTranslations();
  const { space } = useSpace();
  const { integrations } = useImportableIntegrations();
  const [showImport, setShowImport] = useState(false);

  return (
    <div className="flex justify-end gap-2">
      {integrations.length > 0 ? (
        <>
          <Button onClick={() => setShowImport(true)}>{t("import_knowledge")}</Button>
          {showImport && <ImportKnowledgeDialog open={showImport} onOpenChange={setShowImport} />}
        </>
      ) : space.personal ? (
        // No connected integrations yet: connecting them lives on the account page.
        <Button asChild>
          <Link href="/account/integrations">{t("connect_personal_integration")}</Link>
        </Button>
      ) : (
        // Org/shared spaces need an admin-configured tenant app (admin UI is Phase 7).
        <p className="text-muted-foreground self-center text-sm">
          {t("no_integrations_available")}
        </p>
      )}
    </div>
  );
}

export function IntegrationsTab({ canCreate }: { canCreate: boolean }) {
  const t = useTranslations();
  const { space } = useSpace();

  const items = space.knowledge.integration_knowledge_list.items.filter(
    (item) => item.space_id === space.id
  );
  const rows = groupIntegrationRows(items);
  const models = embeddingModelsInUse(items, space.embedding_models);
  const grouped =
    models.length > 1 ||
    space.embedding_models.length > 1 ||
    models.some((model) => !model.inSpace);

  return (
    <div className="flex flex-col gap-4">
      {canCreate && <ImportToolbar />}
      {items.length === 0 ? (
        <EmptyState title={t("no_results")} />
      ) : (
        (grouped ? models : [null]).map((model) => {
          const modelRows = model ? rows.filter((row) => row.embeddingModelId === model.id) : rows;
          if (modelRows.length === 0) return null;
          return (
            <div key={model?.id ?? "all"} className="flex flex-col gap-1">
              {model && (
                <h3 className="text-muted-foreground text-sm font-medium">
                  {model.name}
                  {model.inSpace ? "" : ` (${t("disabled")})`}
                </h3>
              )}
              <IntegrationItemsTable rows={modelRows} />
            </div>
          );
        })
      )}
    </div>
  );
}
