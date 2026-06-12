import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { notFound } from "next/navigation";
import { EneoApiError } from "@/lib/api/errors";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { GroupChatEditor } from "@/features/group-chats/group-chat-editor";
import { groupChatQueryOptions } from "@/features/group-chats/use-group-chat";

export default async function GroupChatEditPage({
  params
}: {
  params: Promise<{ spaceId: string; groupChatId: string }>;
}) {
  const { groupChatId } = await params;
  const queryClient = getQueryClient();

  try {
    await queryClient.fetchQuery(groupChatQueryOptions(eneoApi(), groupChatId));
  } catch (error) {
    if (error instanceof EneoApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <GroupChatEditor groupChatId={groupChatId} />
    </HydrationBoundary>
  );
}
