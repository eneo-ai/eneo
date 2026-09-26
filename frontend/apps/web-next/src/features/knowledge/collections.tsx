"use client";

import { Button as AstryxButton } from "@astryxdesign/core/Button";
import type { DropdownMenuOption } from "@astryxdesign/core/DropdownMenu";
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import {
  pixel,
  proportional,
  Table,
  useTableSortable,
  useTableSortableState,
  type TableColumn,
  type UseTableSortableConfig
} from "@astryxdesign/core/Table";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FolderClosed, FolderInput, Pencil, SearchX, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { StatusLabel } from "@/components/composites/status-label";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { ClientTime } from "@/components/composites/client-time";
import { useRemovalMutation } from "@/features/spaces/removal";
import { useSpace } from "@/features/spaces/use-space";
import { EmbeddingModelSelect } from "./embedding-model-select";
import { embeddingModelsInUse, type Collection } from "./knowledge";
import {
  COLLECTION_COMPARATORS,
  COLLECTION_DEFAULT_SORT,
  type CollectionSortKey
} from "./knowledge-sort";
import { MoveResourceDialog } from "./move-dialog";
import { NoCreatePermissionInfo } from "./no-create-permission-info";
import { filterCollections } from "./table-controls";
import { SpaceTableFrame } from "@/features/spaces/table-frame";
import { KnowledgeNameCell, KnowledgeTableControls } from "./table-controls-ui";

function useInvalidateSpace() {
  const { routeId } = useSpace();
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
}

/** Create dialog (with embedding model choice) or rename dialog. */
function CollectionDialog({
  collection,
  open,
  onOpenChange
}: {
  collection?: Pick<Collection, "id" | "name">;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const router = useRouter();
  const { space, routeId } = useSpace();
  const invalidateSpace = useInvalidateSpace();
  const [name, setName] = useState(collection?.name ?? "");
  const [modelId, setModelId] = useState<string | undefined>(space.embedding_models[0]?.id);

  const save = useMutation({
    mutationFn: async () => {
      if (collection) {
        return unwrap(
          browserApi.POST("/api/v1/groups/{id}/", {
            params: { path: { id: collection.id } },
            body: { name }
          })
        );
      }
      return unwrap(
        browserApi.POST("/api/v1/spaces/{id}/knowledge/groups/", {
          params: { path: { id: space.id } },
          body: { name, embedding_model: modelId ? { id: modelId } : undefined }
        })
      );
    },
    onSuccess: (saved) => {
      invalidateSpace();
      onOpenChange(false);
      if (!collection) {
        setName("");
        router.push(`/spaces/${routeId}/knowledge/collections/${saved.id}`);
      }
    },
    onError: (error) => toastApiError(error, t)
  });

  const noModels = !collection && space.embedding_models.length === 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {collection ? t("edit_collection") : t("create_new_collection")}
          </DialogTitle>
        </DialogHeader>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim()) save.mutate();
          }}
        >
          {noModels && (
            <p className="border-destructive/50 text-destructive rounded-md border px-3 py-2 text-sm">
              <span className="font-bold">{t("warning")}: </span>
              {t("no_embedding_models_warning")}
            </p>
          )}
          <div className="flex flex-col gap-2">
            <Label htmlFor="collection-name">{t("name")}</Label>
            <Input
              id="collection-name"
              value={name}
              required
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          {!collection && (
            <EmbeddingModelSelect
              models={space.embedding_models}
              value={modelId}
              onChange={setModelId}
            />
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={save.isPending || noModels || !name.trim()}>
              {collection
                ? save.isPending
                  ? t("saving")
                  : t("save_changes")
                : save.isPending
                  ? t("creating")
                  : t("create_collection")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** "Skapa samling": opens the create dialog, then goes to the new collection. */
export function CreateCollectionButton() {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  return (
    <>
      <AstryxButton
        label={t("create_collection")}
        variant="primary"
        onClick={() => setOpen(true)}
      />
      {open && <CollectionDialog open={open} onOpenChange={setOpen} />}
    </>
  );
}

/** Row menu for a collection: rename, move to another space, delete. */
export function CollectionActions({ collection }: { collection: Collection }) {
  const t = useTranslations();
  const { space } = useSpace();
  const invalidateSpace = useInvalidateSpace();
  const [showEdit, setShowEdit] = useState(false);
  const [showMove, setShowMove] = useState(false);
  const [showDelete, setShowDelete] = useState(false);

  const canDelete = collection.permissions?.includes("delete") ?? false;

  const deleteCollection = useRemovalMutation({
    mutationFn: () =>
      unwrap(
        browserApi.DELETE("/api/v1/groups/{id}/", { params: { path: { id: collection.id } } })
      ),
    refresh: invalidateSpace,
    onRemoved: () => setShowDelete(false)
  });

  const moveCollection = useRemovalMutation({
    mutationFn: (targetSpaceId: string) =>
      unwrap(
        browserApi.POST("/api/v1/groups/{id}/transfer/", {
          params: { path: { id: collection.id } },
          body: { target_space_id: targetSpaceId }
        })
      ),
    refresh: invalidateSpace,
    onRemoved: () => setShowMove(false)
  });

  const items: DropdownMenuOption[] = [
    { label: t("edit"), icon: <Pencil aria-hidden="true" />, onClick: () => setShowEdit(true) },
    ...(canDelete && !space.organization
      ? [
          {
            label: t("move"),
            icon: <FolderInput aria-hidden="true" />,
            onClick: () => setShowMove(true)
          }
        ]
      : []),
    ...(canDelete
      ? [
          {
            label: t("delete"),
            icon: <Trash2 aria-hidden="true" />,
            variant: "destructive" as const,
            onClick: () => setShowDelete(true)
          }
        ]
      : [])
  ];

  return (
    <>
      <MoreMenu
        label={t("space_more_actions_for", { name: collection.name })}
        items={items}
        alignment="end"
      />
      {showEdit && (
        <CollectionDialog collection={collection} open={showEdit} onOpenChange={setShowEdit} />
      )}
      <MoveResourceDialog
        open={showMove}
        onOpenChange={setShowMove}
        title={t("move_collection")}
        hint={t("move_collection_hint")}
        confirmLabel={t("move_collection")}
        pending={moveCollection.isPending}
        onMove={(targetSpaceId) => moveCollection.mutate(targetSpaceId)}
      />
      {showDelete && (
        <ConfirmDialogControlled
          open={showDelete}
          onOpenChange={setShowDelete}
          title={t("delete_collection")}
          description={t("confirm_delete_collection", { name: collection.name })}
          confirmLabel={deleteCollection.isPending ? t("deleting") : t("delete")}
          pending={deleteCollection.isPending}
          onConfirm={() => deleteCollection.mutate()}
        />
      )}
    </>
  );
}

/** One embedding model's collections; a grouped table is named by its model heading. */
function CollectionsTable({
  collections,
  sortConfig,
  labelledBy
}: {
  collections: Collection[];
  sortConfig: UseTableSortableConfig<CollectionSortKey>;
  labelledBy?: string;
}) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const sortPlugin = useTableSortable<Collection, CollectionSortKey>(sortConfig);

  const columns: TableColumn<Collection>[] = [
    {
      key: "name",
      header: t("name"),
      width: proportional(3),
      sortable: true,
      renderCell: (collection) => (
        <KnowledgeNameCell
          icon={FolderClosed}
          href={`/spaces/${routeId}/knowledge/collections/${collection.id}`}
        >
          {collection.name}
        </KnowledgeNameCell>
      )
    },
    {
      key: "files",
      header: t("content"),
      width: proportional(1),
      sortable: true,
      renderCell: (collection) =>
        t("space_files_count", { count: collection.metadata.num_info_blobs })
    },
    {
      key: "status",
      header: t("status"),
      width: proportional(1),
      renderCell: (collection) =>
        collection.metadata.num_info_blobs > 0 ? (
          <StatusLabel status="success" label={t("space_status_indexed")} />
        ) : (
          <StatusLabel status="neutral" label={t("empty")} />
        )
    },
    {
      key: "updated",
      header: t("space_updated_column"),
      width: proportional(1),
      sortable: true,
      renderCell: (collection) => {
        const updatedAt = collection.updated_at ?? collection.created_at;
        return updatedAt ? <ClientTime value={updatedAt} format="date" /> : "—";
      }
    },
    {
      key: "actions",
      header: <VisuallyHidden>{t("actions")}</VisuallyHidden>,
      width: pixel(64),
      align: "end",
      renderCell: (collection) => <CollectionActions collection={collection} />
    }
  ];

  return (
    <SpaceTableFrame>
      <Table
        data={collections}
        columns={columns}
        idKey="id"
        aria-labelledby={labelledBy}
        plugins={{ sort: sortPlugin }}
      />
    </SpaceTableFrame>
  );
}

export function CollectionsTab({ canCreate }: { canCreate: boolean }) {
  const t = useTranslations();
  const { space } = useSpace();
  const groupId = useId();
  const [filter, setFilter] = useState("");

  const collections = space.knowledge.groups.items.filter(
    (collection) => collection.space_id === space.id
  );
  const visibleCollections = filterCollections(collections, filter);
  // Sorted by the column headers; one sort order across the model groups.
  const { sortedData, sortConfig } = useTableSortableState<Collection, CollectionSortKey>({
    data: visibleCollections,
    defaultSort: COLLECTION_DEFAULT_SORT,
    comparators: COLLECTION_COMPARATORS
  });
  const models = embeddingModelsInUse(visibleCollections, space.embedding_models);
  const grouped =
    models.length > 1 ||
    space.embedding_models.length > 1 ||
    models.some((model) => !model.inSpace);

  const action = canCreate ? (
    <CreateCollectionButton />
  ) : (
    <NoCreatePermissionInfo resourceType={t("resource_collections")} />
  );

  // Nothing to filter yet: the empty state carries the one create button.
  if (collections.length === 0) {
    return (
      <EmptyState
        icon={<FolderClosed />}
        title={t("space_collections_empty_title")}
        description={t("space_collections_empty_description")}
        headingLevel={3}
        actions={action}
      />
    );
  }

  const toolbar = (
    <KnowledgeTableControls
      filterValue={filter}
      onFilterChange={setFilter}
      filterLabel={t("space_filter_collections_label")}
      filterPlaceholder={t("ui_filter_items", { resourceName: t("resource_collections") })}
      resultCount={visibleCollections.length}
    >
      {action}
    </KnowledgeTableControls>
  );

  if (visibleCollections.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        {toolbar}
        <EmptyState
          icon={<SearchX />}
          title={t("ui_no_items_matching", { resourceNamePlural: t("resource_collections") })}
          headingLevel={3}
          isCompact
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {toolbar}
      {(grouped ? models : [null]).map((model) => {
        const rows = model
          ? sortedData.filter((collection) => collection.embedding_model.id === model.id)
          : sortedData;
        const headingId = model ? `${groupId}-${model.id}` : undefined;
        return (
          <div key={model?.id ?? "all"} className="flex flex-col gap-2">
            {model && (
              <h3 id={headingId} className="text-ax-text-secondary text-sm font-semibold">
                {model.name}
                {model.inSpace ? "" : ` (${t("disabled")})`}
              </h3>
            )}
            <CollectionsTable collections={rows} sortConfig={sortConfig} labelledBy={headingId} />
          </div>
        );
      })}
    </div>
  );
}
