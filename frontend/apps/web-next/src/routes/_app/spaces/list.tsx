import { createFileRoute } from "@tanstack/react-router";
import { useTranslations } from "use-intl";
import { SpacesList } from "@/features/spaces/list/spaces-list";
import { spacesListQueryOptions } from "@/features/spaces/space";
import { browserApi } from "@/lib/api/browser";
import { readCached } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/spaces/list")({
  loader: ({ context }) => readCached(context.queryClient, spacesListQueryOptions(browserApi)),
  head: routeTitle("spaces"),
  component: SpacesListPage
});

function SpacesListPage() {
  const t = useTranslations();
  return (
    <div className="flex w-full flex-col gap-6 p-4 md:p-6">
      <SpacesList title={t("spaces")} />
    </div>
  );
}
