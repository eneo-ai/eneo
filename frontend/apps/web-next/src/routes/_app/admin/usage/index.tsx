import { createFileRoute } from "@tanstack/react-router";
import { UsagePage } from "@/features/admin/usage/usage-page";
import { storageSpacesQueryOptions, tokenUsageQueryOptions } from "@/features/admin/usage/usage";
import { storageQueryOptions } from "@/features/storage/storage";
import { browserApi } from "@/lib/api/browser";
import { warmQuery } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/usage/")({
  loader: ({ context: { queryClient } }) => {
    warmQuery(queryClient, tokenUsageQueryOptions(browserApi));
    warmQuery(queryClient, storageQueryOptions(browserApi));
    warmQuery(queryClient, storageSpacesQueryOptions(browserApi));
  },
  head: routeTitle("usage"),
  component: UsagePage
});
