import { createFileRoute } from "@tanstack/react-router";
import { NotFoundPage } from "@/components/shell/not-found-page";
import { SpaceChat } from "@/features/spaces/chat/space-chat.client";

export const Route = createFileRoute("/_app/spaces/$spaceId/chat")({
  notFoundComponent: NotFoundPage,
  component: SpaceChat
});
