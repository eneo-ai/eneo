"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { Button } from "@/components/ui/button";
import { useAppContext } from "@/components/providers/app-context";
import { useSpace } from "@/features/spaces/use-space";
import { embeddingModelsInUse } from "../knowledge";
import { NoCreatePermissionInfo } from "../no-create-permission-info";
import { IntegrationsBetaNotice } from "../notices";
import { groupIntegrationRows } from "./grouping";
import { ImportKnowledgeDialog, useImportableIntegrations } from "./import/import-dialog";
import { integrationSetupAction } from "./setup-action";
import { IntegrationItemsTable } from "./table";

function ImportToolbar() {
  const t = useTranslations();
  const { space } = useSpace();
  const { can } = useAppContext();
  const { integrations } = useImportableIntegrations();
  const [showImport, setShowImport] = useState(false);
  const action = integrationSetupAction({
    importableCount: integrations.length,
    personal: space.personal,
    organization: space.organization,
    isAdmin: can("admin")
  });

  return (
    <div className="flex justify-end gap-2">
      {action.kind === "import" ? (
        <>
          <Button onClick={() => setShowImport(true)}>{t("import_knowledge")}</Button>
          {showImport && <ImportKnowledgeDialog open={showImport} onOpenChange={setShowImport} />}
        </>
      ) : action.kind === "link" ? (
        <Button asChild>
          <Link href={action.href}>{t("configure_integrations")}</Link>
        </Button>
      ) : (
        <p className="text-muted-foreground self-center text-sm">{t(action.messageKey)}</p>
      )}
    </div>
  );
}

export function IntegrationsTab({
  canCreate,
  integrationRequestFormUrl
}: {
  canCreate: boolean;
  integrationRequestFormUrl?: string;
}) {
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
      {integrationRequestFormUrl ? (
        <IntegrationsBetaNotice integrationRequestFormUrl={integrationRequestFormUrl} />
      ) : null}
      {canCreate ? (
        <ImportToolbar />
      ) : (
        <div className="flex justify-end">
          <NoCreatePermissionInfo resourceType={t("resource_integrations")} />
        </div>
      )}
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
