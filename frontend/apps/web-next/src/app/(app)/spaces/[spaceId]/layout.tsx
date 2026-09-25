import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";
import { EneoApiError } from "@/lib/api/errors";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { SpaceFrame } from "@/features/spaces/frame/space-frame";
import { spaceQueryOptions } from "@/features/spaces/space";
import { SpaceProvider } from "@/features/spaces/use-space";

/**
 * The tab title is the space name (or the localized alias for personal/org).
 * Tab pages set their own title, which the template puts in front of it:
 * "Kunskap · Upphandling · Eneo".
 */
export async function generateMetadata({
  params
}: {
  params: Promise<{ spaceId: string }>;
}): Promise<Metadata> {
  const { spaceId } = await params;
  try {
    const space = await getQueryClient().fetchQuery(spaceQueryOptions(eneoApi(), spaceId));
    const t = await getTranslations();
    const name = space.personal
      ? t("personal")
      : space.organization
        ? t("organization")
        : space.name;
    return { title: { default: name, template: `%s · ${name} · Eneo` } };
  } catch {
    return {};
  }
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
    await queryClient.fetchQuery(spaceQueryOptions(eneoApi(), spaceId));
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
