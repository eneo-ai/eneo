import { createFileRoute, notFound } from "@tanstack/react-router";
import { HelpAssistantEditor } from "@/features/admin/help-assistants/help-assistant-editor";
import { helpRoleQueryOptions } from "@/features/admin/help-assistants/help-assistants";
import { assistantQueryOptions } from "@/features/assistants/editor/use-assistant";
import { PROMPT_GUIDE_KIND } from "@/features/help-assistants/prompt-guide/helper-runs";
import { spaceQueryOptions } from "@/features/spaces/space";
import { SpaceProvider } from "@/features/spaces/use-space";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/help-assistants/$kind")({
  loader: async ({ context: { queryClient }, params }) => {
    if (params.kind !== PROMPT_GUIDE_KIND) throw notFound();
    const role = await readFresh(queryClient, helpRoleQueryOptions(browserApi, params.kind));
    if (!role) throw notFound();
    await Promise.all([
      readFresh(queryClient, assistantQueryOptions(browserApi, role.assistant_id)),
      readFresh(queryClient, spaceQueryOptions(browserApi, "organization"))
    ]);
    return role;
  },
  head: routeTitle("admin_help_assistants_nav_label"),
  component: HelpAssistantRoute
});

function HelpAssistantRoute() {
  const role = Route.useLoaderData();
  return (
    <SpaceProvider routeId="organization">
      <HelpAssistantEditor
        key={role.assistant_id}
        assistantId={role.assistant_id}
        helperKind={role.kind}
      />
    </SpaceProvider>
  );
}
