import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { notFound } from "next/navigation";
import { EneoApiError } from "@/lib/api/errors";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { AssistantEditor } from "@/features/assistants/editor/assistant-editor";
import { assistantQueryOptions } from "@/features/assistants/editor/use-assistant";

export default async function AssistantEditPage({
  params
}: {
  params: Promise<{ spaceId: string; assistantId: string }>;
}) {
  const { assistantId } = await params;
  const queryClient = getQueryClient();

  try {
    await queryClient.fetchQuery(assistantQueryOptions(eneoApi(), assistantId));
  } catch (error) {
    if (error instanceof EneoApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <AssistantEditor assistantId={assistantId} />
    </HydrationBoundary>
  );
}
