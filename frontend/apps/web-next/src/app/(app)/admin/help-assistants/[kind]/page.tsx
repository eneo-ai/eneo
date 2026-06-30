import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { notFound } from "next/navigation";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { assistantQueryOptions } from "@/features/assistants/editor/use-assistant";
import {
  helpRoleQueryOptions,
  type HelperKind
} from "@/features/admin/help-assistants/help-assistants";
import { HelpAssistantEditor } from "@/features/admin/help-assistants/help-assistant-editor";
import { spaceQueryOptions } from "@/features/spaces/space";
import { SpaceProvider } from "@/features/spaces/use-space";
import { pageTitle } from "@/lib/page-metadata";

export const generateMetadata = pageTitle("admin_help_assistants_nav_label");

export default async function HelpAssistantEditRoute({
  params
}: {
  params: Promise<{ kind: string }>;
}) {
  const { kind } = await params;
  const queryClient = getQueryClient();
  const api = eneoApi();

  const role = await queryClient.fetchQuery(helpRoleQueryOptions(api, kind as HelperKind));
  if (!role) notFound();

  await Promise.all([
    queryClient.fetchQuery(assistantQueryOptions(api, role.assistant_id)),
    queryClient.fetchQuery(spaceQueryOptions(api, "organization"))
  ]);

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <SpaceProvider routeId="organization">
        <HelpAssistantEditor assistantId={role.assistant_id} helperKind={kind as HelperKind} />
      </SpaceProvider>
    </HydrationBoundary>
  );
}
