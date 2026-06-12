"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FolderClosed, MoreHorizontal, Pencil, FolderInput, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { useSpace } from "@/features/spaces/use-space";
import { EmbeddingModelSelect } from "./embedding-model-select";
import { embeddingModelsInUse, type Collection } from "./knowledge";
import { MoveResourceDialog } from "./move-dialog";

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

function CreateCollectionButton() {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>{t("create_collection")}</Button>
      {open && <CollectionDialog open={open} onOpenChange={setOpen} />}
    </>
  );
}

function CollectionActions({ collection }: { collection: Collection }) {
  const t = useTranslations();
  const { space } = useSpace();
  const invalidateSpace = useInvalidateSpace();
  const [showEdit, setShowEdit] = useState(false);
  const [showMove, setShowMove] = useState(false);
  const [showDelete, setShowDelete] = useState(false);

  const canDelete = collection.permissions?.includes("delete") ?? false;

  const deleteCollection = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.DELETE("/api/v1/groups/{id}/", { params: { path: { id: collection.id } } })
      ),
    onSuccess: () => {
      invalidateSpace();
      setShowDelete(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const moveCollection = useMutation({
    mutationFn: (targetSpaceId: string) =>
      unwrap(
        browserApi.POST("/api/v1/groups/{id}/transfer/", {
          params: { path: { id: collection.id } },
          body: { target_space_id: targetSpaceId }
        })
      ),
    onSuccess: () => {
      invalidateSpace();
      setShowMove(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" aria-label={t("actions")}>
            <MoreHorizontal className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={() => setShowEdit(true)}>
            <Pencil className="size-4" /> {t("edit")}
          </DropdownMenuItem>
          {canDelete && !space.organization && (
            <DropdownMenuItem onSelect={() => setShowMove(true)}>
              <FolderInput className="size-4" /> {t("move")}
            </DropdownMenuItem>
          )}
          {canDelete && (
            <DropdownMenuItem variant="destructive" onSelect={() => setShowDelete(true)}>
              <Trash2 className="size-4" /> {t("delete")}
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
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

function CollectionRows({ collections }: { collections: Collection[] }) {
  const t = useTranslations();
  const { routeId } = useSpace();
  return (
    <>
      {collections.map((collection) => (
        <TableRow key={collection.id}>
          <TableCell>
            <Link
              href={`/spaces/${routeId}/knowledge/collections/${collection.id}`}
              className="flex items-center gap-2 font-medium hover:underline"
            >
              <FolderClosed className="text-muted-foreground size-4" />
              {collection.name}
            </Link>
          </TableCell>
          <TableCell>
            {collection.metadata.num_info_blobs > 0 ? (
              <Badge variant="secondary">
                {t("files", { count: collection.metadata.num_info_blobs })}
              </Badge>
            ) : (
              <Badge variant="outline">{t("empty")}</Badge>
            )}
          </TableCell>
          <TableCell className="text-right">
            <CollectionActions collection={collection} />
          </TableCell>
        </TableRow>
      ))}
    </>
  );
}

export function CollectionsTab({ canCreate }: { canCreate: boolean }) {
  const t = useTranslations();
  const { space } = useSpace();

  const collections = space.knowledge.groups.items.filter(
    (collection) => collection.space_id === space.id
  );
  const models = embeddingModelsInUse(collections, space.embedding_models);
  const grouped =
    models.length > 1 ||
    space.embedding_models.length > 1 ||
    models.some((model) => !model.inSpace);

  const toolbar = canCreate ? (
    <div className="flex justify-end">
      <CreateCollectionButton />
    </div>
  ) : null;

  if (collections.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        {toolbar}
        <EmptyState title={t("there_are_currently_no_collections_configured")} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {toolbar}
      {(grouped ? models : [null]).map((model) => {
        const rows = model
          ? collections.filter((collection) => collection.embedding_model.id === model.id)
          : collections;
        return (
          <div key={model?.id ?? "all"} className="flex flex-col gap-1">
            {model && (
              <h3 className="text-muted-foreground text-sm font-medium">
                {model.name}
                {model.inSpace ? "" : ` (${t("disabled")})`}
              </h3>
            )}
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("name")}</TableHead>
                  <TableHead>{t("files_header")}</TableHead>
                  <TableHead className="w-16" />
                </TableRow>
              </TableHeader>
              <TableBody>
                <CollectionRows collections={rows} />
              </TableBody>
            </Table>
          </div>
        );
      })}
    </div>
  );
}
