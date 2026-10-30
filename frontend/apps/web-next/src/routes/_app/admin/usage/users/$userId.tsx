import { createFileRoute } from "@tanstack/react-router";
import { UserUsagePage } from "@/features/admin/usage/user-usage-page";
import {
  usageRangeFromSearchParams,
  userModelBreakdownQueryOptions,
  userTokenUsageSummaryQueryOptions
} from "@/features/admin/usage/usage";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";
import { notFoundOn404 } from "@/lib/route-helpers";
import { parseSearch } from "@/lib/router/search";

export const Route = createFileRoute("/_app/admin/usage/users/$userId")({
  loader: {
    staleReloadMode: "blocking",
    handler: async ({ context: { queryClient }, params, location }) => {
      const range = usageRangeFromSearchParams(parseSearch(location.searchStr));
      await notFoundOn404(
        Promise.all([
          readFresh(
            queryClient,
            userTokenUsageSummaryQueryOptions(browserApi, params.userId, range)
          ),
          readFresh(queryClient, userModelBreakdownQueryOptions(browserApi, params.userId, range))
        ])
      );
      return { range };
    }
  },
  head: routeTitle("usage"),
  remountDeps: ({ params }) => params.userId,
  component: UserUsageRoute
});

function UserUsageRoute() {
  const { userId } = Route.useParams();
  const { range } = Route.useLoaderData();
  return <UserUsagePage userId={userId} initialRange={range} />;
}
