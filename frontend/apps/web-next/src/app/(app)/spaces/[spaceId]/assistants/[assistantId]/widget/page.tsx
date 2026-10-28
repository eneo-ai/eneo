import type { Metadata } from "next";
import { dehydrate, HydrationBoundary, noop } from "@tanstack/react-query";
import { notFound, redirect } from "next/navigation";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { hasPermission } from "@/lib/auth/permissions";
import { env } from "@/lib/env";
import { getWidgetLoaderBundle } from "@/lib/server/widget-loader";
import { assistantQueryOptions } from "@/features/assistants/editor/use-assistant";
import { spacePageTitle } from "@/features/spaces/page-title";
import { spaceQueryOptions } from "@/features/spaces/space";
import {
  spaceWidgetsQueryOptions,
  widgetPolicyQueryOptions,
  widgetTemplatesQueryOptions
} from "@/features/widget/admin/queries";
import { WidgetAdminPage } from "@/features/widget/admin/widget-admin-page";

export async function generateMetadata({
  params
}: {
  params: Promise<{ assistantId: string }>;
}): Promise<Metadata> {
  const { assistantId } = await params;
  return spacePageTitle(async (t) => {
    const assistant = await getQueryClient().query(assistantQueryOptions(eneoApi(), assistantId));
    return `${assistant.name} – ${t("widget_admin_title")}`;
  }, "assistants");
}

/**
 * The web widget of one assistant. The widgets permission unlocks the
 * feature; the backend enforces it too. Only what the snippet needs of the
 * loader build travels to the browser; the source stays on the server.
 */
export default async function AssistantWidgetPage({
  params
}: {
  params: Promise<{ spaceId: string; assistantId: string }>;
}) {
  const { spaceId, assistantId } = await params;
  const api = eneoApi();
  const user = await unwrap(api.GET("/api/v1/users/me/"));
  if (!hasPermission(user)("widgets")) {
    redirect(`/spaces/${spaceId}/assistants/${assistantId}/edit`);
  }

  const queryClient = getQueryClient();
  let space;
  try {
    [space] = await Promise.all([
      queryClient.query(spaceQueryOptions(api, spaceId)),
      queryClient.query(assistantQueryOptions(api, assistantId))
    ]);
  } catch (error) {
    if (error instanceof EneoApiError && error.status === 404) notFound();
    throw error;
  }
  await Promise.all([
    queryClient.query(spaceWidgetsQueryOptions(api, space.id)),
    queryClient.query(widgetPolicyQueryOptions(api)).catch(noop),
    queryClient.query(widgetTemplatesQueryOptions(api)).catch(noop)
  ]);

  const bundle = await getWidgetLoaderBundle();
  const release = bundle
    ? { version: bundle.version, channel: bundle.channel, integrity: bundle.integrity }
    : null;

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <WidgetAdminPage assistantId={assistantId} release={release} appOrigin={env.APP_ORIGIN} />
    </HydrationBoundary>
  );
}
