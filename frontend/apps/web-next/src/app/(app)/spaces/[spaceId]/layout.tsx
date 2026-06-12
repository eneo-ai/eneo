import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { notFound } from "next/navigation";
import { EneoApiError } from "@/lib/api/errors";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { spaceQueryOptions } from "@/features/spaces/space";
import { SpaceProvider } from "@/features/spaces/use-space";
import { SpaceNav } from "./space-nav.client";

export default async function SpaceLayout({
  children,
  params
}: {
  children: React.ReactNode;
  params: Promise<{ spaceId: string }>;
}) {
  const { spaceId } = await params;
  const queryClient = getQueryClient();

  try {
    await queryClient.fetchQuery(spaceQueryOptions(eneoApi(), spaceId));
  } catch (error) {
    if (error instanceof EneoApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <SpaceProvider routeId={spaceId}>
        <div className="flex min-h-0 flex-1">
          <aside className="bg-sidebar hidden w-56 shrink-0 overflow-y-auto border-r p-3 md:block">
            <SpaceNav />
          </aside>
          <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto p-6">{children}</div>
        </div>
      </SpaceProvider>
    </HydrationBoundary>
  );
}
