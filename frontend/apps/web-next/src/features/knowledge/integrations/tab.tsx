"use client";

import { Button } from "@astryxdesign/core/Button";
import { Plug } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { useAppContext } from "@/components/providers/app-context";
import { useSpace } from "@/features/spaces/use-space";
import { embeddingModelsInUse } from "../knowledge";
import { NoCreatePermissionInfo } from "../no-create-permission-info";
import { IntegrationsBetaNotice } from "../notices";
import { groupIntegrationRows } from "./grouping";
import { ImportKnowledgeDialog, useImportableIntegrations } from "./import/import-dialog";
import { integrationSetupAction } from "./setup-action";
import { IntegrationItemsTable } from "./table";

/** Import from a connected integration, or where to connect one first. */
function ImportAction() {
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

  if (action.kind === "import") {
    return (
      <>
        <Button
          label={t("import_knowledge")}
          variant="primary"
          onClick={() => setShowImport(true)}
        />
        {showImport && <ImportKnowledgeDialog open={showImport} onOpenChange={setShowImport} />}
      </>
    );
  }
  if (action.kind === "link") {
    return <Button label={t("configure_integrations")} href={action.href} />;
  }
  return <p className="text-ax-text-secondary text-sm">{t(action.messageKey)}</p>;
}

/** The integrations tab; `labelledBy` is the tab, which names an ungrouped table. */
export function IntegrationsTab({
  canCreate,
  integrationRequestFormUrl,
  labelledBy
}: {
  canCreate: boolean;
  integrationRequestFormUrl?: string;
  labelledBy: string;
}) {
  const t = useTranslations();
  const { space } = useSpace();
  const groupId = useId();

  const items = space.knowledge.integration_knowledge_list.items.filter(
    (item) => item.space_id === space.id
  );
  const rows = groupIntegrationRows(items);
  const models = embeddingModelsInUse(items, space.embedding_models);
  const grouped =
    models.length > 1 ||
    space.embedding_models.length > 1 ||
    models.some((model) => !model.inSpace);
  const action = canCreate ? (
    <ImportAction />
  ) : (
    <NoCreatePermissionInfo resourceType={t("resource_integrations")} />
  );

  return (
    <div className="flex flex-col gap-4">
      {integrationRequestFormUrl ? (
        <IntegrationsBetaNotice integrationRequestFormUrl={integrationRequestFormUrl} />
      ) : null}
      {items.length === 0 ? (
        // Nothing to list yet: the empty state carries the one action.
        <EmptyState
          icon={<Plug />}
          title={t("fix_integrations_empty_title")}
          headingLevel={3}
          actions={action}
        />
      ) : (
        <>
          <div className="flex flex-wrap justify-end gap-2">{action}</div>
          {(grouped ? models : [null]).map((model) => {
            const modelRows = model
              ? rows.filter((row) => row.embeddingModelId === model.id)
              : rows;
            if (modelRows.length === 0) return null;
            const headingId = model ? `${groupId}-${model.id}` : undefined;
            return (
              <div key={model?.id ?? "all"} className="flex flex-col gap-2">
                {model && (
                  <h3 id={headingId} className="text-ax-text-secondary text-sm font-semibold">
                    {model.name}
                    {model.inSpace ? "" : ` (${t("disabled")})`}
                  </h3>
                )}
                <IntegrationItemsTable rows={modelRows} labelledBy={headingId ?? labelledBy} />
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}
