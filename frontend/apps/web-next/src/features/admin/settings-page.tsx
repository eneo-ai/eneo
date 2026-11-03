import { useTranslations } from "use-intl";
import { PageHeader } from "@/components/composites/page-header";
import { RetentionPolicySection } from "./audit/retention-policy-section";
import { FeatureToggles } from "./feature-toggles";

export function AdminSettingsPage() {
  const t = useTranslations();
  return (
    <div className="flex w-full max-w-4xl flex-col gap-6">
      <PageHeader title={t("settings")} description={t("admin_organisation_description")} />
      <FeatureToggles />
      <RetentionPolicySection />
    </div>
  );
}
