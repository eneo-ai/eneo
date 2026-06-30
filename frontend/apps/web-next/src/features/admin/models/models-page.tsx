"use client";

import { useSuspenseQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { PageHeader } from "@/components/composites/page-header";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger
} from "@/components/ui/accordion";
import { securityClassificationsQueryOptions } from "@/features/admin/security-classifications/security-classifications";
import { browserApi } from "@/lib/api/browser";
import { MigrationHistoryPanel } from "./migration-history-panel";
import { adminModelsQueryOptions } from "./models";
import { PricingVisibilityToggle } from "./pricing-visibility-toggle";
import { ProviderOverview } from "./provider-overview";

/**
 * Admin model management, grouped by provider. Each provider card surfaces its
 * API-key status alongside its models (enable/disable, set-default, security
 * classification, edit). Custom providers add models via the auto-fetch wizard.
 * Pricing visibility + migration history live under "Advanced".
 */
export function ModelsPage() {
  const t = useTranslations();
  const { data: models } = useSuspenseQuery(adminModelsQueryOptions(browserApi));
  const { data: security } = useSuspenseQuery(securityClassificationsQueryOptions(browserApi));

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader title={t("models")} />

      <ProviderOverview
        models={models}
        classifications={security.security_classifications}
        securityEnabled={security.security_enabled}
      />

      <Accordion type="single" collapsible className="w-full">
        <AccordionItem value="advanced">
          <AccordionTrigger>{t("advanced")}</AccordionTrigger>
          <AccordionContent className="flex flex-col gap-6 pt-2">
            <PricingVisibilityToggle />
            <MigrationHistoryPanel />
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </div>
  );
}
