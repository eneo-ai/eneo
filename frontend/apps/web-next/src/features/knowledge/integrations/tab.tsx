"use client";

import { Button } from "@astryxdesign/core/Button";
import { useCollator } from "@astryxdesign/core/i18n";
import { Plug } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { AREA_HUES } from "@/components/composites/icon-tile";
import { useAppContext } from "@/components/providers/app-context";
import { useSpace } from "@/features/spaces/use-space";
import { embeddingModelsInUse } from "../knowledge";
import { NoCreatePermissionInfo } from "../no-create-permission-info";
import { IntegrationsBetaNotice } from "../notices";
import { ImportKnowledgeDialog, useImportableIntegrations } from "./import/import-dialog";
import { integrationSetupAction } from "./setup-action";
import { SourcesList, type SourceGroup } from "./sources-table";
import { groupIntegrationSources } from "./sources";
import { useSyncProgress } from "./use-sync-progress";

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
  const collator = useCollator();
  const { space } = useSpace();

  const items = space.knowledge.integration_knowledge_list.items.filter(
    (item) => item.space_id === space.id
  );
  const sources = groupIntegrationSources(items, collator.compare);
  const { progress, queued, loaded: progressLoaded } = useSyncProgress();
  const models = embeddingModelsInUse(items, space.embedding_models);
  const grouped =
    models.length > 1 ||
    space.embedding_models.length > 1 ||
    models.some((model) => !model.inSpace);
  const groups: SourceGroup[] = grouped
    ? models.flatMap((model) => {
        const modelSources = sources.filter((source) => source.embeddingModelId === model.id);
        return modelSources.length === 0
          ? []
          : [
              {
                key: model.id,
                heading: model.inSpace ? model.name : `${model.name} (${t("disabled")})`,
                sources: modelSources
              }
            ];
      })
    : [{ key: "all", heading: null, sources }];
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
          hue={AREA_HUES.knowledge}
          title={t("fix_integrations_empty_title")}
          headingLevel={3}
          actions={action}
        />
      ) : (
        <>
          <div className="flex flex-wrap justify-end gap-2">{action}</div>
          <SourcesList
            groups={groups}
            progress={progress}
            queued={queued}
            progressLoaded={progressLoaded}
            labelledBy={labelledBy}
          />
        </>
      )}
    </div>
  );
}
