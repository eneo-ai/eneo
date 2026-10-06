import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { EneoApiError } from "@/lib/api/errors";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { SpaceFrame } from "@/features/spaces/frame/space-frame";
import { spaceLayoutTitle } from "@/features/spaces/page-title";
import { spaceQueryOptions } from "@/features/spaces/space";
import { SpaceProvider } from "@/features/spaces/use-space";

/** The tab title is the space's name; pages below put their own in front of it. */
export async function generateMetadata({
  params
}: {
  params: Promise<{ spaceId: string }>;
}): Promise<Metadata> {
  const { spaceId } = await params;
  return spaceLayoutTitle(() => getQueryClient().query(spaceQueryOptions(eneoApi(), spaceId)));
}

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
    await queryClient.query(spaceQueryOptions(eneoApi(), spaceId));
  } catch (error) {
    if (error instanceof EneoApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <SpaceProvider routeId={spaceId}>
        <SpaceFrame>{children}</SpaceFrame>
      </SpaceProvider>
    </HydrationBoundary>
  );
}
