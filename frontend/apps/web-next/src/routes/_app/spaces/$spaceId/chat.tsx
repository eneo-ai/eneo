import { createFileRoute } from "@tanstack/react-router";
import { SpaceChat } from "@/features/spaces/chat/space-chat.client";

export const Route = createFileRoute("/_app/spaces/$spaceId/chat")({
  component: SpaceChat
});
