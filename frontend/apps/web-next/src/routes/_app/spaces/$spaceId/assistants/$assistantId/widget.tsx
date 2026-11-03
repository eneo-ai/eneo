import { createFileRoute } from "@tanstack/react-router";
import { WidgetAdminPage } from "@/features/widget/admin/widget-admin-page";
import {
  spaceWidgetsQueryOptions,
  widgetPolicyQueryOptions,
  widgetTemplatesQueryOptions
} from "@/features/widget/admin/queries";
import { assistantQueryOptions } from "@/features/assistants/editor/use-assistant";
import { spaceQueryOptions } from "@/features/spaces/space";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";
import { notFoundOn404, requirePermission } from "@/lib/route-helpers";
import type { LoaderRelease } from "@/features/widget/admin/snippet";

async function loaderRelease(): Promise<LoaderRelease | null> {
  const response = await fetch("/widget/manifest.json", { cache: "no-store" });
  return response.ok ? response.json() : null;
}

export const Route = createFileRoute("/_app/spaces/$spaceId/assistants/$assistantId/widget")({
  beforeLoad: ({ context, params }) =>
    requirePermission(
      context,
      "widgets",
      `/spaces/${params.spaceId}/assistants/${params.assistantId}/edit`
    ),
  loader: async ({ context: { queryClient }, params }) => {
    const [space] = await Promise.all([
      notFoundOn404(readFresh(queryClient, spaceQueryOptions(browserApi, params.spaceId))),
      notFoundOn404(readFresh(queryClient, assistantQueryOptions(browserApi, params.assistantId)))
    ]);
    const [, , , release] = await Promise.all([
      readFresh(queryClient, spaceWidgetsQueryOptions(browserApi, space.id)),
      readFresh(queryClient, widgetPolicyQueryOptions(browserApi)),
      readFresh(queryClient, widgetTemplatesQueryOptions(browserApi)),
      loaderRelease().catch(() => null)
    ]);
    return { release };
  },
  head: routeTitle("widget_admin_title"),
  remountDeps: ({ params }) => params.assistantId,
  component: Page
});
function Page() {
  return (
    <WidgetAdminPage
      assistantId={Route.useParams().assistantId}
      release={Route.useLoaderData().release}
      appOrigin={location.origin}
    />
  );
}
