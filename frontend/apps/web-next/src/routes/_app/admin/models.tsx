import { createFileRoute } from "@tanstack/react-router";
import { ModelsPage } from "@/features/admin/models/models-page";
import { adminModelsQueryOptions } from "@/features/admin/models/models";
import {
  modelProvidersQueryOptions,
  providerCapabilitiesQueryOptions
} from "@/features/admin/models/model-providers";
import { kindFilterOf, modelsHref } from "@/features/admin/models/provider-sections";
import { securityClassificationsQueryOptions } from "@/features/admin/security-classifications/security-classifications";
import { browserApi } from "@/lib/api/browser";
import { readFresh, warmQuery } from "@/lib/api/query";
import { useRouter } from "@/lib/navigation";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/models")({
  validateSearch: (search: Record<string, unknown>) => {
    const kind = kindFilterOf(typeof search.type === "string" ? search.type : undefined);
    return { type: kind === "all" ? undefined : kind };
  },
  loader: async ({ context: { queryClient } }) => {
    warmQuery(queryClient, modelProvidersQueryOptions(browserApi));
    warmQuery(queryClient, providerCapabilitiesQueryOptions(browserApi));
    await Promise.all([
      readFresh(queryClient, adminModelsQueryOptions(browserApi)),
      readFresh(queryClient, securityClassificationsQueryOptions(browserApi))
    ]);
  },
  head: routeTitle("models"),
  component: RouteComponent
});

function RouteComponent() {
  const { type } = Route.useSearch();
  const router = useRouter();
  return (
    <ModelsPage
      kind={type}
      onKindChange={(kind) => router.replace(modelsHref(kind), { scroll: false })}
    />
  );
}
