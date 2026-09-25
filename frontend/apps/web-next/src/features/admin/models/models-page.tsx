"use client";

import { Button } from "@astryxdesign/core/Button";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { useSuspenseQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";
import { PageHeader } from "@/components/composites/page-header";
import { securityClassificationsQueryOptions } from "@/features/admin/security-classifications/security-classifications";
import { browserApi } from "@/lib/api/browser";
import { rescueFocus } from "@/features/admin/users/focus-rescue";
import { AddModelWizard } from "./add-model-wizard";
import { MigrationHistoryPanel } from "./migration-history-panel";
import { adminModelsQueryOptions } from "./models";
import { PricingVisibilityToggle } from "./pricing-visibility-toggle";
import { ProviderOverview } from "./provider-overview";

type ModelsTab = "models" | "history" | "settings";
const TABS: ModelsTab[] = ["models", "history", "settings"];

/**
 * Admin model management. "Modeller" groups the models by provider (API-key
 * status, enable/disable, default, security classification, edit, migrate);
 * "Migreringshistorik" lists past migrations; "Inställningar" holds the
 * org-wide pricing visibility. "Lägg till leverantör" and each provider's
 * "Lägg till modell" open the same add-model wizard.
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

  const baseId = useId();
  const panelId = `${baseId}-panel`;
  const panelRef = useRef<HTMLDivElement>(null);
  const tabId = (value: ModelsTab) => `${baseId}-tab-${value}`;
  const tabLabel = (value: ModelsTab) =>
    value === "models"
      ? t("models")
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
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5">
      <PageHeader
        title={t("models")}
        description={t("admin_models_description")}
        breadcrumbs={[
          { label: t("admin_breadcrumb_root"), href: "/admin" },
          { label: t("admin_section_configuration") }
        ]}
        tour="admin-models"
        actions={
          <Button
            variant="primary"
            label={t("add_provider")}
            icon={<Plus className="size-4" aria-hidden="true" />}
            onClick={openAddProvider}
          />
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
          a delete removed the focused row or card (see rescueFocus). */}
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
            <ProviderOverview
              models={models}
              classifications={security.security_classifications}
              securityEnabled={security.security_enabled}
              onAddModel={openAddModel}
              onAddProvider={openAddProvider}
              onRemoved={() => rescueFocus(panelRef.current)}
            />
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
