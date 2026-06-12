"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, Pencil, RefreshCw, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog";
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
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { useJobs } from "@/features/jobs/use-jobs";
import { useSpace } from "@/features/spaces/use-space";
import type { IntegrationKnowledge } from "../knowledge";

/** Row actions (rename / full sync / delete) for one integration knowledge item. */
export function IntegrationActions({ item }: { item: IntegrationKnowledge }) {
  const t = useTranslations();
  const { space } = useSpace();
  const { trackJob } = useJobs();
  const invalidate = useSpaceInvalidation();
  const [showRename, setShowRename] = useState(false);
  const [showSync, setShowSync] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [newName, setNewName] = useState(item.name);

  const canEdit = item.permissions?.includes("edit") ?? false;
  const canDelete = item.permissions?.includes("delete") ?? false;

  const rename = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.PATCH("/api/v1/spaces/{id}/knowledge/integrations/{integration_knowledge_id}/", {
          params: { path: { id: space.id, integration_knowledge_id: item.id } },
          body: { name: newName }
        })
      ),
    onSuccess: () => {
      invalidate();
      setShowRename(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const fullSync = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST(
          "/api/v1/spaces/{id}/knowledge/integrations/{integration_knowledge_id}/sync/",
          { params: { path: { id: space.id, integration_knowledge_id: item.id } } }
        )
      ),
    onSuccess: () => {
      trackJob();
      invalidate();
      setShowSync(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const deleteKnowledge = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.DELETE(
          "/api/v1/spaces/{id}/knowledge/integrations/remove/{integration_knowledge_id}/",
          { params: { path: { id: space.id, integration_knowledge_id: item.id } } }
        )
      ),
    onSuccess: () => {
      invalidate();
      setShowDelete(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  if (!canEdit && !canDelete) return null;

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" aria-label={t("actions")}>
            <MoreHorizontal className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {canEdit && (
            <DropdownMenuItem
              onSelect={() => {
                setNewName(item.name);
                setShowRename(true);
              }}
            >
              <Pencil className="size-4" /> {t("rename")}
            </DropdownMenuItem>
          )}
          {canEdit && item.integration_type === "sharepoint" && (
            <DropdownMenuItem onSelect={() => setShowSync(true)}>
              <RefreshCw className="size-4" /> {t("trigger_full_sync")}
            </DropdownMenuItem>
          )}
          {canDelete && (
            <DropdownMenuItem variant="destructive" onSelect={() => setShowDelete(true)}>
              <Trash2 className="size-4" /> {t("delete")}
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <RenameDialog
        open={showRename}
        onOpenChange={setShowRename}
        title={t("integration_rename_title")}
        name={newName}
        onNameChange={setNewName}
        pending={rename.isPending}
        onSave={() => rename.mutate()}
      />
      <AlertDialog open={showSync} onOpenChange={setShowSync}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("trigger_full_sync")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("confirm_full_sync", { knowledgeName: item.name })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={fullSync.isPending}>{t("cancel")}</AlertDialogCancel>
            <Button disabled={fullSync.isPending} onClick={() => fullSync.mutate()}>
              {fullSync.isPending ? t("syncing") : t("start_full_sync")}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <ConfirmDialogControlled
        open={showDelete}
        onOpenChange={setShowDelete}
        title={t("delete_integration_knowledge")}
        description={t("confirm_delete_integration_knowledge", { knowledgeName: item.name })}
        confirmLabel={deleteKnowledge.isPending ? t("deleting") : t("delete")}
        pending={deleteKnowledge.isPending}
        onConfirm={() => deleteKnowledge.mutate()}
      />
    </>
  );
}

/** Wrapper actions (rename / delete all items) shown on folder rows and the wrapper page. */
export function WrapperActions({
  wrapperId,
  wrapperName,
  itemCount,
  canEdit,
  canDelete,
  onDeleted
}: {
  wrapperId: string;
  wrapperName: string;
  itemCount: number;
  canEdit: boolean;
  canDelete: boolean;
  onDeleted?: () => void;
}) {
  const t = useTranslations();
  const { space } = useSpace();
  const invalidate = useSpaceInvalidation();
  const [showRename, setShowRename] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [newName, setNewName] = useState(wrapperName);

  const rename = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.PATCH("/api/v1/spaces/{id}/knowledge/integrations/wrappers/{wrapper_id}/", {
          params: { path: { id: space.id, wrapper_id: wrapperId } },
          body: { name: newName }
        })
      ),
    onSuccess: () => {
      invalidate();
      setShowRename(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const deleteWrapper = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.DELETE("/api/v1/spaces/{id}/knowledge/integrations/wrappers/{wrapper_id}/", {
          params: { path: { id: space.id, wrapper_id: wrapperId } }
        })
      ),
    onSuccess: () => {
      invalidate();
      setShowDelete(false);
      onDeleted?.();
    },
    onError: (error) => toastApiError(error, t)
  });

  if (!canEdit && !canDelete) return null;

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" aria-label={t("actions")}>
            <MoreHorizontal className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {canEdit && (
            <DropdownMenuItem
              onSelect={() => {
                setNewName(wrapperName);
                setShowRename(true);
              }}
            >
              <Pencil className="size-4" /> {t("rename_wrapper")}
            </DropdownMenuItem>
          )}
          {canDelete && (
            <DropdownMenuItem variant="destructive" onSelect={() => setShowDelete(true)}>
              <Trash2 className="size-4" /> {t("delete_wrapper")}
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <RenameDialog
        open={showRename}
        onOpenChange={setShowRename}
        title={t("rename_wrapper")}
        name={newName}
        onNameChange={setNewName}
        pending={rename.isPending}
        onSave={() => rename.mutate()}
      />
      <ConfirmDialogControlled
        open={showDelete}
        onOpenChange={setShowDelete}
        title={t("delete_wrapper")}
        description={t("confirm_delete_sharepoint_wrapper", {
          wrapperName,
          count: String(itemCount)
        })}
        confirmLabel={deleteWrapper.isPending ? t("deleting") : t("delete")}
        pending={deleteWrapper.isPending}
        onConfirm={() => deleteWrapper.mutate()}
      />
    </>
  );
}

function RenameDialog({
  open,
  onOpenChange,
  title,
  name,
  onNameChange,
  pending,
  onSave
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  name: string;
  onNameChange: (name: string) => void;
  pending: boolean;
  onSave: () => void;
}) {
  const t = useTranslations();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          <Label htmlFor="integration-name">{t("name")}</Label>
          <Input
            id="integration-name"
            value={name}
            onChange={(event) => onNameChange(event.target.value)}
          />
        </div>
        <DialogFooter>
          <Button variant="outline" disabled={pending} onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button disabled={pending || !name.trim()} onClick={onSave}>
            {pending ? t("saving") : t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function useSpaceInvalidation() {
  const { routeId } = useSpace();
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
}
