import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { notFound } from "next/navigation";
import { EneoApiError } from "@/lib/api/errors";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { pageTitle } from "@/lib/page-metadata";
import {
  usageRangeFromSearchParams,
  userModelBreakdownQueryOptions,
  userTokenUsageSummaryQueryOptions
} from "@/features/admin/usage/usage";
import { UserUsagePage } from "@/features/admin/usage/user-usage-page";

export const generateMetadata = pageTitle("usage");

export default async function AdminUserUsageRoute({
  params,
  searchParams
}: {
  params: Promise<{ userId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { userId } = await params;
  const range = usageRangeFromSearchParams(await searchParams);
  const queryClient = getQueryClient();
  const api = eneoApi();

  try {
    await Promise.all([
      queryClient.fetchQuery(userTokenUsageSummaryQueryOptions(api, userId, range)),
      queryClient.fetchQuery(userModelBreakdownQueryOptions(api, userId, range))
    ]);
  } catch (error) {
    if (error instanceof EneoApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <UserUsagePage userId={userId} initialRange={range} />
    </HydrationBoundary>
  );
}
