import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { getTranslations } from "next-intl/server";
import { getQueryClient } from "@/lib/api/query";
import { eneoApi } from "@/lib/api/server";
import { spacesListQueryOptions } from "@/features/spaces/space";
import { SpacesList } from "./spaces-list.client";

export default async function SpacesListPage() {
  const t = await getTranslations();
  const queryClient = getQueryClient();
  await queryClient.fetchQuery(spacesListQueryOptions(eneoApi()));

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-6">
      <HydrationBoundary state={dehydrate(queryClient)}>
        <SpacesList title={t("spaces")} />
      </HydrationBoundary>
    </div>
  );
}
