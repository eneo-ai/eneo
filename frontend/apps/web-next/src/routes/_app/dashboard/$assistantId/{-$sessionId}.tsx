import { createFileRoute } from "@tanstack/react-router";
import { NotFoundPage } from "@/components/shell/not-found-page";
import { DashboardChat } from "@/features/dashboard/dashboard-chat.client";

export const Route = createFileRoute("/_app/dashboard/$assistantId/{-$sessionId}")({
  notFoundComponent: NotFoundPage,
  remountDeps: ({ params }) => params.assistantId,
  component: DashboardChatPage
});

function DashboardChatPage() {
  const { assistantId, sessionId } = Route.useParams();
  return <DashboardChat assistantId={assistantId} sessionId={sessionId ?? null} />;
}
