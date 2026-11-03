import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/spaces/$spaceId/")({
  beforeLoad: ({ params }) => {
    throw redirect({
      to: params.spaceId === "personal" ? "/spaces/$spaceId/chat" : "/spaces/$spaceId/overview",
      params: { spaceId: params.spaceId },
      replace: true
    });
  }
});
