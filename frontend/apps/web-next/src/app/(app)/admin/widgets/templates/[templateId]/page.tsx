import type { Metadata } from "next";
import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import { EneoApiError } from "@/lib/api/errors";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { widgetTemplateQueryOptions } from "@/features/widget/admin/org/queries";
import { WidgetTemplatePage } from "@/features/widget/admin/org/widget-template-page";

type Params = Promise<{ templateId: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { templateId } = await params;
  const t = await getTranslations();
  const template = await getQueryClient()
    .query(widgetTemplateQueryOptions(eneoApi(), templateId))
    .catch(() => null);
  return {
    title: template
      ? `${template.name} – ${t("widget_admin_templates")}`
      : t("widget_admin_templates")
  };
}

export default async function AdminWidgetTemplateRoute({ params }: { params: Params }) {
  const { templateId } = await params;
  const queryClient = getQueryClient();
  try {
    await queryClient.query(widgetTemplateQueryOptions(eneoApi(), templateId));
  } catch (error) {
    if (error instanceof EneoApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <WidgetTemplatePage templateId={templateId} />
    </HydrationBoundary>
  );
}
