import { getTranslations } from "next-intl/server";
import { PageHeader } from "@/components/composites/page-header";
import { pageTitle } from "@/lib/page-metadata";
import { RetentionPolicySection } from "@/features/admin/audit/retention-policy-section";
import { FeatureToggles } from "@/features/admin/feature-toggles";

export const generateMetadata = pageTitle("settings");

/** Organisation-wide settings: the tenant feature toggles (moved here from the admin landing) and the audit retention policy. */
export default async function AdminSettingsPage() {
  const t = await getTranslations();
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
