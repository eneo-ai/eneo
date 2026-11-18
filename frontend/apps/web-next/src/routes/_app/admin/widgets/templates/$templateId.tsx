import { createFileRoute } from "@tanstack/react-router";
import { WidgetTemplatePage } from "@/features/widget/admin/org/widget-template-page";
import { widgetTemplateQueryOptions } from "@/features/widget/admin/org/queries";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";
import { notFoundOn404 } from "@/lib/route-helpers";

export const Route = createFileRoute("/_app/admin/widgets/templates/$templateId")({
  loader: ({ context: { queryClient }, params }) =>
    notFoundOn404(
      readFresh(queryClient, widgetTemplateQueryOptions(browserApi, params.templateId))
    ),
  head: routeTitle("widget_admin_templates"),
  remountDeps: ({ params }) => params.templateId,
  component: Page
});
function Page() {
  return <WidgetTemplatePage templateId={Route.useParams().templateId} />;
}
