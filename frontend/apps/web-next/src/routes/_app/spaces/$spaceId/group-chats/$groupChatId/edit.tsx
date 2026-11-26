import { createFileRoute } from "@tanstack/react-router";
import { GroupChatEditor } from "@/features/group-chats/group-chat-editor";
import { groupChatQueryOptions } from "@/features/group-chats/use-group-chat";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { spaceTitle } from "@/lib/route-head";
import { notFoundOn404 } from "@/lib/route-helpers";

export const Route = createFileRoute("/_app/spaces/$spaceId/group-chats/$groupChatId/edit")({
  loader: {
    staleReloadMode: "blocking",
    handler: async ({ context, params }) => {
      const { name } = await notFoundOn404(
        readFresh(context.queryClient, groupChatQueryOptions(browserApi, params.groupChatId))
      );
      return { name };
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
  remountDeps: ({ params }) => params.groupChatId,
  component: GroupChatEditPage
});

function GroupChatEditPage() {
  return <GroupChatEditor groupChatId={Route.useParams().groupChatId} />;
}
