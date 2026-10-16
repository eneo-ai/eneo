"use client";

import type { DropdownMenuOption } from "@astryxdesign/core/DropdownMenu";
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import {
  useMutation,
  useMutationState,
  useQueryClient,
  type QueryClient
} from "@tanstack/react-query";
import { Pencil, RefreshCw, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { flushSync } from "react-dom";
import { FieldProblem, fieldProblemProps } from "@/components/composites/field-problem";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { browserApi } from "@/lib/api/browser";
import { getErrorMessage, unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import { useJobs } from "@/features/jobs/use-jobs";
import { useRemovalMutation } from "@/features/spaces/removal";
import { useSpace } from "@/features/spaces/use-space";
import type { IntegrationKnowledge } from "../knowledge";
import type { IntegrationSource } from "./sources";

type SourceRef = Pick<IntegrationSource, "kind" | "id">;

/** Marks a removal from the source's own page (the actions given `onDeleted`). */
function sourceRemovalKey(spaceId: string, source: SourceRef) {
  return ["integrations", "remove", spaceId, source.kind, source.id];
}

/** Mutation ids grow, so a mutation started later has a higher one. */
function latestMutationId(queryClient: QueryClient): number {
  return queryClient
    .getMutationCache()
    .getAll()
    .reduce((latest, mutation) => Math.max(latest, mutation.mutationId), 0);
}

/**
 * The source is being deleted or was deleted from this page, so a page that
 * showed only it is leaving rather than looking at a source that went away.
 * Only the page's own actions mark a removal, and one from before the page
 * opened (on an earlier visit that Back can return to) does not count: the
 * source is then simply gone.
 */
export function useIsRemovingSource(spaceId: string, source: SourceRef): boolean {
  const queryClient = useQueryClient();
  const [openedAfter] = useState(() => latestMutationId(queryClient));
  const statuses = useMutationState({
    filters: {
      mutationKey: sourceRemovalKey(spaceId, source),
      predicate: (mutation) => mutation.mutationId > openedAfter
    },
    select: (mutation) => mutation.state.status
  });
  return statuses.some((status) => status === "pending" || status === "success");
}

/**
 * Row actions (rename / full sync / delete) for one integration knowledge item.
 * `onDeleted` runs once the deleted item has left the space, e.g. to leave a
 * page that only showed it (`useIsRemovingSource`).
 */
export function IntegrationActions({
  item,
  onDeleted
}: {
  item: IntegrationKnowledge;
  onDeleted?: () => void;
}) {
  const t = useTranslations();
  const { space } = useSpace();
  const { trackJob } = useJobs();
  const queryClient = useQueryClient();
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
    onSuccess: (job) => {
      trackJob(job);
      invalidate();
      void queryClient.invalidateQueries({
        queryKey: ["integrations", "sync-progress", space.id]
      });
      setShowSync(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const deleteKnowledge = useRemovalMutation({
    mutationKey: onDeleted ? sourceRemovalKey(space.id, { kind: "item", id: item.id }) : undefined,
    mutationFn: () =>
      unwrap(
        browserApi.DELETE(
          "/api/v1/spaces/{id}/knowledge/integrations/remove/{integration_knowledge_id}/",
          { params: { path: { id: space.id, integration_knowledge_id: item.id } } }
        )
      ),
    refresh: invalidate,
    onRemoved: () => {
      setShowDelete(false);
      onDeleted?.();
    }
  });

  if (!canEdit && !canDelete) return null;

  const items: DropdownMenuOption[] = [
    ...(canEdit
      ? [
          {
            label: t("rename"),
            icon: <Pencil aria-hidden="true" />,
            onClick: () => {
              setNewName(item.name);
              setShowRename(true);
            }
          }
        ]
      : []),
    ...(canEdit && item.integration_type === "sharepoint"
      ? [
          {
            label: t("trigger_full_sync"),
            icon: <RefreshCw aria-hidden="true" />,
            onClick: () => setShowSync(true)
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
        label={t("space_more_actions_for", { name: item.name })}
        items={items}
        alignment="end"
      />
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
            {/* Busy, it stays enabled so it keeps focus; a second press is ignored. */}
            <Button
              aria-busy={fullSync.isPending || undefined}
              onClick={() => {
                if (!fullSync.isPending) fullSync.mutate();
              }}
            >
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

/**
 * Wrapper actions (rename / resync every item / delete all items) shown on
 * source rows and the wrapper page. `items` are the wrapper's items.
 */
export function WrapperActions({
  wrapperId,
  wrapperName,
  items: wrapperItems,
  canEdit,
  canDelete,
  onDeleted
}: {
  wrapperId: string;
  wrapperName: string;
  items: IntegrationKnowledge[];
  canEdit: boolean;
  canDelete: boolean;
  onDeleted?: () => void;
}) {
  const t = useTranslations();
  const { space } = useSpace();
  const { trackJob } = useJobs();
  const queryClient = useQueryClient();
  const invalidate = useSpaceInvalidation();
  const [showRename, setShowRename] = useState(false);
  const [showResync, setShowResync] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [newName, setNewName] = useState(wrapperName);

  const resyncable = wrapperItems.filter(
    (item) =>
      item.integration_type === "sharepoint" && (item.permissions?.includes("edit") ?? false)
  );
  const canResync = canEdit && resyncable.length > 0;

  // Never rejects: confirming again after a failure would queue the items
  // that were queued already once more.
  const resync = useMutation({
    mutationFn: async () => {
      const results = await Promise.allSettled(
        resyncable.map((item) =>
          unwrap(
            browserApi.POST(
              "/api/v1/spaces/{id}/knowledge/integrations/{integration_knowledge_id}/sync/",
              { params: { path: { id: space.id, integration_knowledge_id: item.id } } }
            )
          )
        )
      );
      const jobs = results.flatMap((result) =>
        result.status === "fulfilled" ? [result.value] : []
      );
      const refused = results.find(
        (result): result is PromiseRejectedResult => result.status === "rejected"
      );
      return { jobs, total: results.length, refusal: refused?.reason as unknown };
    },
    onSuccess: ({ jobs, total, refusal }) => {
      if (jobs.length > 0) trackJob(jobs);
      invalidate();
      void queryClient.invalidateQueries({
        queryKey: ["integrations", "sync-progress", space.id]
      });
      setShowResync(false);
      const failed = total - jobs.length;
      if (failed > 0) {
        toast.error(
          total === 1
            ? t("resync_all_wrapper_failed_one")
            : t("resync_all_wrapper_partial_failure", { failed, total }),
          // The first refusal's reason, in the catalog's words as toastApiError gives them.
          { description: getErrorMessage(refusal, t) }
        );
      } else {
        toast.success(
          total === 1
            ? t("resync_all_wrapper_queued_one")
            : t("resync_all_wrapper_queued", { count: total })
        );
      }
    }
  });

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

  const deleteWrapper = useRemovalMutation({
    mutationKey: onDeleted
      ? sourceRemovalKey(space.id, { kind: "wrapper", id: wrapperId })
      : undefined,
    mutationFn: () =>
      unwrap(
        browserApi.DELETE("/api/v1/spaces/{id}/knowledge/integrations/wrappers/{wrapper_id}/", {
          params: { path: { id: space.id, wrapper_id: wrapperId } }
        })
      ),
    refresh: invalidate,
    onRemoved: () => {
      setShowDelete(false);
      onDeleted?.();
    }
  });

  if (!canEdit && !canDelete) return null;

  const items: DropdownMenuOption[] = [
    ...(canEdit
      ? [
          {
            label: t("rename_wrapper"),
            icon: <Pencil aria-hidden="true" />,
            onClick: () => {
              setNewName(wrapperName);
              setShowRename(true);
            }
          }
        ]
      : []),
    ...(canResync
      ? [
          {
            label: t("resync_all_wrapper"),
            icon: <RefreshCw aria-hidden="true" />,
            onClick: () => setShowResync(true)
          }
        ]
      : []),
    ...(canDelete
      ? [
          {
            label: t("delete_wrapper"),
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
        label={t("space_more_actions_for", { name: wrapperName })}
        items={items}
        alignment="end"
      />
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
        open={showResync}
        onOpenChange={setShowResync}
        title={t("resync_all_wrapper")}
        description={
          resyncable.length === 1
            ? t("confirm_resync_all_wrapper_one", { wrapperName })
            : t("confirm_resync_all_wrapper", { wrapperName, count: resyncable.length })
        }
        confirmLabel={resync.isPending ? t("syncing") : t("start_full_sync")}
        variant="default"
        pending={resync.isPending}
        onConfirm={() => resync.mutate()}
      />
      <ConfirmDialogControlled
        open={showDelete}
        onOpenChange={setShowDelete}
        title={t("delete_wrapper")}
        description={t("confirm_delete_sharepoint_wrapper", {
          wrapperName,
          count: String(wrapperItems.length)
        })}
        confirmLabel={deleteWrapper.isPending ? t("deleting") : t("delete")}
        pending={deleteWrapper.isPending}
        onConfirm={() => deleteWrapper.mutate()}
      />
    </>
  );
}

/** Renames an integration. An empty name shows at the field on save, which takes focus. */
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
  const [submitted, setSubmitted] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const nameProblem = submitted && !name.trim() ? t("required_field") : null;

  function save() {
    if (pending) return;
    if (!name.trim()) {
      // Rendered before focus moves, so the field is read with its error.
      flushSync(() => setSubmitted(true));
      nameRef.current?.focus();
      return;
    }
    onSave();
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setSubmitted(false);
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          <Label htmlFor="integration-name">{t("name")}</Label>
          <Input
            ref={nameRef}
            id="integration-name"
            value={name}
            onChange={(event) => onNameChange(event.target.value)}
            {...fieldProblemProps("integration-name", nameProblem)}
          />
          <FieldProblem id="integration-name" problem={nameProblem} />
        </div>
        <DialogFooter>
          <Button variant="outline" disabled={pending} onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          {/* Never disabled: busy, it keeps focus and a second press is ignored. */}
          <Button aria-busy={pending || undefined} onClick={save}>
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
