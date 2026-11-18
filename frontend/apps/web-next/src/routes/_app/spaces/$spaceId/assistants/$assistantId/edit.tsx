import { createFileRoute, redirect } from "@tanstack/react-router";
import { AssistantEditor } from "@/features/assistants/editor/assistant-editor";
import { assistantQueryOptions } from "@/features/assistants/editor/use-assistant";
import { promptGuideAvailabilityQueryOptions } from "@/features/help-assistants/prompt-guide/helper-runs";
import { browserApi } from "@/lib/api/browser";
import { readFresh, warmQuery } from "@/lib/api/query";
import { spaceTitle } from "@/lib/route-head";
import { notFoundOn404 } from "@/lib/route-helpers";

export const Route = createFileRoute("/_app/spaces/$spaceId/assistants/$assistantId/edit")({
  loader: {
    staleReloadMode: "blocking",
    handler: async ({ context, params }) => {
      const assistant = await notFoundOn404(
        readFresh(context.queryClient, assistantQueryOptions(browserApi, params.assistantId))
      );
      if (assistant.is_help_assistant)
        throw redirect({ href: "/admin/help-assistants", replace: true });
      warmQuery(
        context.queryClient,
        promptGuideAvailabilityQueryOptions(browserApi, params.assistantId)
      );
      return { name: assistant.name };
    }
  },
  head: ({ matches, match, loaderData }) =>
    spaceTitle(
      matches,
      match.context.t,
      loaderData
        ? match.context.t("space_edit_title", { name: loaderData.name })
        : match.context.t("assistants")
    ),
  remountDeps: ({ params }) => params.assistantId,
  component: AssistantEditPage
});

function AssistantEditPage() {
  return <AssistantEditor assistantId={Route.useParams().assistantId} />;
}
