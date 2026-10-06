import { DashboardChat } from "./dashboard-chat.client";

export default async function DashboardChatPage({
  params
}: {
  params: Promise<{ assistantId: string; sessionId?: string[] }>;
}) {
  const { assistantId, sessionId } = await params;
  return <DashboardChat assistantId={assistantId} sessionId={sessionId?.[0] ?? null} />;
}
