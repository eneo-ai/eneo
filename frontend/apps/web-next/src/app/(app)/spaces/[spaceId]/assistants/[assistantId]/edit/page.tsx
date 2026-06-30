import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { notFound, redirect } from "next/navigation";
import { EneoApiError } from "@/lib/api/errors";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { AssistantEditor } from "@/features/assistants/editor/assistant-editor";
import { assistantQueryOptions } from "@/features/assistants/editor/use-assistant";
import { promptGuideAvailabilityQueryOptions } from "@/features/help-assistants/prompt-guide/helper-runs";

export default async function AssistantEditPage({
  params
}: {
  params: Promise<{ spaceId: string; assistantId: string }>;
}) {
  const { assistantId } = await params;
  const queryClient = getQueryClient();
  const api = eneoApi();

  try {
    const assistant = await queryClient.fetchQuery(assistantQueryOptions(api, assistantId));
    if (assistant.is_help_assistant) redirect("/admin/help-assistants");
  } catch (error) {
    if (error instanceof EneoApiError && error.status === 404) notFound();
    throw error;
  }

  await queryClient
    .prefetchQuery(promptGuideAvailabilityQueryOptions(api, assistantId))
    .catch(() => {
      // The availability check only controls the optional Prompt Guide button.
    });

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <AssistantEditor assistantId={assistantId} />
    </HydrationBoundary>
  );
}
