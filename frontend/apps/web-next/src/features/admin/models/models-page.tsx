import { Button } from "@astryxdesign/core/Button";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { useQuery, useSuspenseQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useTranslations } from "use-intl";
import { useId, useRef, useState } from "react";
import { PageHeader } from "@/components/composites/page-header";
import { blockingError } from "@/components/composites/query-state";
import { securityClassificationsQueryOptions } from "@/features/admin/security-classifications/security-classifications";
import { browserApi } from "@/lib/api/browser";
import { RemovalFocusScope } from "@/features/spaces/removal";
import { AddModelWizard } from "./add-model-wizard";
import { MigrationHistoryPanel } from "./migration-history-panel";
import { adminModelsQueryOptions } from "./models";
import { PricingVisibilityToggle } from "./pricing-visibility-toggle";
import { ProviderOverview } from "./provider-overview";
import {
  TranscriptionServicesSection,
  type TranscriptionServicesHandle
} from "./transcription-services-section";
import { transcriptionServicesQueryOptions } from "./transcription-services";

type ModelsTab = "models" | "speakers" | "history" | "settings";
const TABS: ModelsTab[] = ["models", "speakers", "history", "settings"];

/**
 * Admin model management. "Leverantörer" groups the models by provider (API-key
 * status, enable/disable, default, security classification, edit, migrate);
 * "Ordtider och talaridentifiering" connects the services that time the words
 * of a transcript and label its speakers; "Migreringshistorik" lists past
 * migrations; "Inställningar" holds the org-wide pricing visibility. "Lägg
 * till leverantör" and each provider's "Lägg till modell" open the same
 * add-model wizard; on the services tab the header's action is "Anslut tjänst".
 */
export function ModelsPage() {
  const t = useTranslations();
  const { data: models } = useSuspenseQuery(adminModelsQueryOptions(browserApi));
  const { data: security } = useSuspenseQuery(securityClassificationsQueryOptions(browserApi));

  const [tab, setTab] = useState<ModelsTab>("models");
  // Tabs stay mounted once opened (hidden when inactive), so the model filters
  // survive a look at the history; the history still loads on first visit.
  const [visited, setVisited] = useState<ReadonlySet<ModelsTab>>(() => new Set(["models"]));
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardProviderId, setWizardProviderId] = useState<string | undefined>(undefined);
  const services = useRef<TranscriptionServicesHandle>(null);
  // The section's own list (shared cache): a list that failed to load offers no connection.
  const servicesQuery = useQuery({
    ...transcriptionServicesQueryOptions(browserApi),
    enabled: tab === "speakers"
  });

  const baseId = useId();
  const panelId = `${baseId}-panel`;
  const panelRef = useRef<HTMLDivElement>(null);
  const tabId = (value: ModelsTab) => `${baseId}-tab-${value}`;
  const tabLabel = (value: ModelsTab) =>
    value === "models"
      ? t("admin_models_providers_tab")
      : value === "speakers"
        ? t("speaker_identification")
        : value === "history"
          ? t("migration_history_title")
          : t("settings");

  function selectTab(next: ModelsTab) {
    setTab(next);
    setVisited((current) => (current.has(next) ? current : new Set([...current, next])));
  }

  function openAddProvider() {
    setWizardProviderId(undefined);
    setWizardOpen(true);
  }

  function openAddModel(providerId: string) {
    setWizardProviderId(providerId);
    setWizardOpen(true);
  }

  return (
    <div className="flex w-full flex-col gap-5">
      <PageHeader
        title={t("models")}
        description={t("admin_models_description")}
        tour="admin-models"
        // Each tab keeps an action here, so the tab strip stays put when switching tabs.
        actions={
          tab !== "speakers" ? (
            <Button
              variant="primary"
              label={t("add_provider")}
              icon={<Plus className="size-4" aria-hidden="true" />}
              onClick={openAddProvider}
            />
          ) : blockingError(servicesQuery) ? undefined : (
            <Button
              variant="primary"
              label={t("speaker_service_connect")}
              icon={<Plus className="size-4" aria-hidden="true" />}
              onClick={() => services.current?.connect()}
            />
          )
        }
      />

      <TabList
        role="tablist"
        aria-label={t("admin_models_tabs_label")}
        value={tab}
        onChange={(value) => selectTab(value as ModelsTab)}
        hasDivider
      >
        {TABS.map((value) => (
          <Tab
            key={value}
            id={tabId(value)}
            value={value}
            label={tabLabel(value)}
            panelId={panelId}
          />
        ))}
      </TabList>

      {/* One panel whose content follows the selected tab, so every tab's
          aria-controls points at an element that exists. It takes focus when
          a delete removed the focused row or card (RemovalFocusScope). */}
      <div
        ref={panelRef}
        role="tabpanel"
        id={panelId}
        aria-labelledby={tabId(tab)}
        tabIndex={-1}
        className="focus-visible:outline-ring rounded-ax-element focus-visible:outline-2 focus-visible:outline-offset-4"
      >
        {visited.has("models") && (
          <div hidden={tab !== "models"}>
            <RemovalFocusScope target={panelRef}>
              <ProviderOverview
                models={models}
                classifications={security.security_classifications}
                securityEnabled={security.security_enabled}
                onAddModel={openAddModel}
                onAddProvider={openAddProvider}
              />
            </RemovalFocusScope>
          </div>
        )}
        {visited.has("speakers") && (
          <div hidden={tab !== "speakers"}>
            <RemovalFocusScope target={panelRef}>
              <TranscriptionServicesSection
                ref={services}
                classifications={security.security_classifications}
              />
            </RemovalFocusScope>
          </div>
        )}
        {visited.has("history") && (
          <div hidden={tab !== "history"}>
            <MigrationHistoryPanel />
          </div>
        )}
        {visited.has("settings") && (
          <div hidden={tab !== "settings"}>
            <PricingVisibilityToggle />
          </div>
        )}
      </div>

      <AddModelWizard
        open={wizardOpen}
        onOpenChange={setWizardOpen}
        initialProviderId={wizardProviderId}
      />
    </div>
  );
}
