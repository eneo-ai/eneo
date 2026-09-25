"use client";

import { Button as AstryxButton } from "@astryxdesign/core/Button";
import { useCollator } from "@astryxdesign/core/i18n";
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import { useSuspenseQuery } from "@tanstack/react-query";
import { LayoutGrid, SearchX, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { EntityAvatar } from "@/components/composites/entity-avatar";
import { iconUrl } from "@/components/composites/icon-field";
import { PageHeader } from "@/components/composites/page-header";
import { RESOURCE_GRID_CLASS, ResourceCard } from "@/components/composites/resource-tile";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { CreateSpaceDialog } from "@/features/spaces/create-space-dialog";
import { filterSpaceResources } from "@/features/spaces/resource-filter";
import { ResourceFilterInput } from "@/features/spaces/resource-filter-input";
import { spaceRouteId, spacesListQueryOptions, type SpaceSparse } from "@/features/spaces/space";
import { DeleteSpaceDialog } from "./delete-space-dialog";

/** "3 assistenter · 1 app", from the counts the list endpoint includes. */
function spaceMeta(space: SpaceSparse, t: ReturnType<typeof useTranslations>): string[] {
  const applications = space.applications;
  if (!applications) return [];
  const assistants = applications.assistants.count + applications.group_chats.count;
  return [
    t("space_assistants_count", { count: assistants }),
    t("space_apps_count", { count: applications.apps.count })
  ];
}

function SpaceCard({
  space,
  onDelete
}: {
  space: SpaceSparse;
  onDelete: (space: SpaceSparse) => void;
}) {
  const t = useTranslations();
  const canDelete = space.permissions?.includes("delete") ?? false;
  const description = space.description?.trim();

  return (
    <ResourceCard
      href={`/spaces/${spaceRouteId(space)}/overview`}
      name={space.name}
      tile={
        <EntityAvatar
          name={space.name}
          id={space.id}
          src={iconUrl(space.icon_id)}
          size="lg"
          className="size-9"
        />
      }
      description={
        description || <span className="text-ax-text-tertiary">{t("space_no_description")}</span>
      }
      meta={spaceMeta(space, t)}
      actions={
        canDelete ? (
          <MoreMenu
            label={t("space_more_actions_for", { name: space.name })}
            alignment="end"
            items={[
              {
                label: t("delete_space"),
                icon: <Trash2 aria-hidden="true" />,
                variant: "destructive",
                onClick: () => onDelete(space)
              }
            ]}
          />
        ) : null
      }
    />
  );
}

export function SpacesList({ title }: { title: string }) {
  const t = useTranslations();
  const { can } = useAppContext();
  const { data: spaces } = useSuspenseQuery(spacesListQueryOptions(browserApi));
  const collator = useCollator();
  const [filter, setFilter] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<SpaceSparse | null>(null);
  const [creating, setCreating] = useState(false);

  // Personal and organization spaces have their own surfaces.
  const sharedSpaces = spaces
    .filter((space) => !space.personal && !space.organization)
    .sort((a, b) => collator.compare(a.name, b.name));
  const visibleSpaces = filterSpaceResources(sharedSpaces, filter);
  const canCreate = can("shared_spaces");
  const createButton = (
    <AstryxButton label={t("create_space")} variant="primary" onClick={() => setCreating(true)} />
  );

  return (
    <>
      <PageHeader
        title={title}
        description={t("space_list_description")}
        actions={canCreate && sharedSpaces.length > 0 ? createButton : undefined}
      />
      {sharedSpaces.length === 0 ? (
        <EmptyState
          icon={<LayoutGrid />}
          title={t("space_list_empty_title")}
          description={
            canCreate ? t("space_list_empty_description") : t("space_list_empty_no_create")
          }
          actions={canCreate ? createButton : undefined}
        />
      ) : (
        <>
          <ResourceFilterInput
            value={filter}
            onChange={setFilter}
            label={t("space_list_filter_label")}
            placeholder={t("space_list_filter_placeholder")}
          />
          {visibleSpaces.length === 0 ? (
            <EmptyState icon={<SearchX />} title={t("no_results_found")} isCompact />
          ) : (
            <ul className={RESOURCE_GRID_CLASS}>
              {visibleSpaces.map((space) => (
                <li key={space.id} className="min-w-0">
                  <SpaceCard space={space} onDelete={setDeleteTarget} />
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {canCreate ? <CreateSpaceDialog open={creating} onOpenChange={setCreating} /> : null}
      <DeleteSpaceDialog space={deleteTarget} onClose={() => setDeleteTarget(null)} />
    </>
  );
}
