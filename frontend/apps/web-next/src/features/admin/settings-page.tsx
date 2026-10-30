"use client";

import { useTranslations } from "use-intl";
import { PageHeader } from "@/components/composites/page-header";
import { RetentionPolicySection } from "./audit/retention-policy-section";
import { FeatureToggles } from "./feature-toggles";

export function AdminSettingsPage() {
  const t = useTranslations();
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
      <PageHeader
        title={t("settings")}
        description={t("admin_organisation_description")}
        breadcrumbs={[
          { label: t("admin_breadcrumb_root"), href: "/admin" },
          { label: t("admin_section_organisation") }
        ]}
      />
      <FeatureToggles />
      <RetentionPolicySection />
    </div>
  );
}
