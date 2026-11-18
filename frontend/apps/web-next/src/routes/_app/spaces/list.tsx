import { createFileRoute } from "@tanstack/react-router";
import { useTranslations } from "use-intl";
import { PageFrame } from "@/components/composites/page-frame";
import { SpacesList } from "@/features/spaces/list/spaces-list";
import { spacesListQueryOptions } from "@/features/spaces/space";
import { browserApi } from "@/lib/api/browser";
import { readCached } from "@/lib/api/query";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/spaces/list")({
  loader: ({ context }) => readCached(context.queryClient, spacesListQueryOptions(browserApi)),
  head: routeTitle("your_spaces"),
  component: SpacesListPage
});

function SpacesListPage() {
  const t = useTranslations();
  return (
    <PageFrame className="gap-6">
      {/* Svelte's title for the list; the top bar's area is Delat. */}
      <SpacesList title={t("your_spaces")} />
    </PageFrame>
  );
}
