import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { notFound } from "next/navigation";
import { EneoApiError } from "@/lib/api/errors";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { appQueryOptions } from "@/features/apps/apps";
import { AppEditor } from "@/features/apps/editor/app-editor";

export default async function AppEditPage({
  params
}: {
  params: Promise<{ spaceId: string; appId: string }>;
}) {
  const { appId } = await params;
  const queryClient = getQueryClient();

  try {
    await queryClient.fetchQuery(appQueryOptions(eneoApi(), appId));
  } catch (error) {
    if (error instanceof EneoApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <AppEditor appId={appId} />
    </HydrationBoundary>
  );
}
