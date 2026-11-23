import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/spaces/$spaceId/group-chats/$groupChatId/edit")({
  beforeLoad: ({ params }) => {
    throw redirect({
      to: "/spaces/$spaceId/assistants/$assistantId/edit",
      params: { spaceId: params.spaceId, assistantId: params.groupChatId },
      replace: true
    });
  }
});
