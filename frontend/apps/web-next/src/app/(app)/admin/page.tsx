import { getTranslations } from "next-intl/server";
import { PageHeader } from "@/components/composites/page-header";
import { FeatureToggles } from "@/features/admin/feature-toggles";

export default async function AdminOverviewPage() {
  const t = await getTranslations();
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
      <PageHeader title={t("organisation")} />
      <FeatureToggles />
    </div>
  );
}
