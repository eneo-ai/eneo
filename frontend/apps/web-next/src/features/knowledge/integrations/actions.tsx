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
import { useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { FieldProblem, fieldProblemProps } from "@/components/composites/field-problem";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
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
import { settleWithLimit } from "@/lib/settle-with-limit";
import { toast } from "@/lib/toast";
import { useJobs } from "@/features/jobs/use-jobs";
import { useRemovalMutation } from "@/features/spaces/removal";
import { useSpace } from "@/features/spaces/use-space";
import type { IntegrationKnowledge } from "../knowledge";
import { KNOWLEDGE_NAME_MAX_LENGTH } from "./knowledge-names";
import { trackSyncs } from "./pending-syncs";
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
 * page that only showed it (`useIsRemovingSource`). While `syncActive` (a sync
 * of the item is queued or running) another would only queue a second.
 */
export function IntegrationActions({
  item,
  syncActive = false,
  onDeleted
}: {
  item: IntegrationKnowledge;
  syncActive?: boolean;
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
  // In the item's row, so its removal can hand focus to the next row.
  const anchor = useRef<HTMLSpanElement>(null);

  const canEdit = item.permissions?.includes("edit") ?? false;
  const canDelete = item.permissions?.includes("delete") ?? false;

  const rename = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.PATCH("/api/v1/spaces/{id}/knowledge/integrations/{integration_knowledge_id}/", {
          params: { path: { id: space.id, integration_knowledge_id: item.id } },
          body: { name: newName.trim() }
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
      // The item reads as queued until the worker reports on it or the job is over.
      trackSyncs([{ jobId: job.id, knowledgeId: item.id }]);
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
    anchor,
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
            label: syncActive ? t("integration_sync_already_running") : t("trigger_full_sync"),
            icon: <RefreshCw aria-hidden="true" />,
            isDisabled: syncActive,
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
      <span ref={anchor} className="contents">
        <MoreMenu
          label={t("space_more_actions_for", { name: item.name })}
          items={items}
          alignment="end"
        />
      </span>
      <RenameDialog
        open={showRename}
        onOpenChange={setShowRename}
        title={t("integration_rename_title")}
        name={newName}
        onNameChange={setNewName}
        pending={rename.isPending}
        onSave={() => rename.mutate()}
      />
      <ConfirmDialogControlled
        open={showSync}
        onOpenChange={setShowSync}
        title={t("trigger_full_sync")}
        description={t("confirm_full_sync", { knowledgeName: item.name })}
        confirmLabel={fullSync.isPending ? t("syncing") : t("start_full_sync")}
        variant="default"
        pending={fullSync.isPending}
        onConfirm={() => fullSync.mutate()}
      />
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

const RESYNC_CONCURRENCY = 4;
/** Folders that could not be queued are named up to this many; the count tells the rest. */
const NAMED_FAILURES = 5;

/**
 * Wrapper actions (rename / resync every item / delete all items) shown on
 * source rows and the wrapper page. `items` are the wrapper's items;
 * `syncActive` says a sync of one of them is queued or running.
 */
export function WrapperActions({
  wrapperId,
  wrapperName,
  items: wrapperItems,
  canEdit,
  canDelete,
  syncActive = false,
  onDeleted
}: {
  wrapperId: string;
  wrapperName: string;
  items: IntegrationKnowledge[];
  canEdit: boolean;
  canDelete: boolean;
  syncActive?: boolean;
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
  const anchor = useRef<HTMLSpanElement>(null);

  const resyncable = wrapperItems.filter(
    (item) =>
      item.integration_type === "sharepoint" && (item.permissions?.includes("edit") ?? false)
  );
  const canResync = canEdit && resyncable.length > 0;

  // Never rejects: confirming again after a failure would queue the items
  // that were queued already once more. A few at a time: each request also
  // checks the site's change subscription.
  const resync = useMutation({
    mutationFn: async () => {
      const results = await settleWithLimit(resyncable, RESYNC_CONCURRENCY, (item) =>
        unwrap(
          browserApi.POST(
            "/api/v1/spaces/{id}/knowledge/integrations/{integration_knowledge_id}/sync/",
            { params: { path: { id: space.id, integration_knowledge_id: item.id } } }
          )
        )
      );
      const queued = resyncable.flatMap((item, index) => {
        const result = results[index];
        return result?.status === "fulfilled"
          ? [{ jobId: result.value.id, knowledgeId: item.id }]
          : [];
      });
      const jobs = results.flatMap((result) =>
        result.status === "fulfilled" ? [result.value] : []
      );
      const refused = results.find(
        (result): result is PromiseRejectedResult => result.status === "rejected"
      );
      const failedNames = resyncable
        .filter((_, index) => results[index]?.status === "rejected")
        .map((item) => item.name);
      return {
        jobs,
        queued,
        total: results.length,
        failedNames,
        refusal: refused?.reason as unknown
      };
    },
    onSuccess: ({ jobs, queued, total, failedNames, refusal }) => {
      trackSyncs(queued);
      if (jobs.length > 0) trackJob(jobs);
      invalidate();
      void queryClient.invalidateQueries({
        queryKey: ["integrations", "sync-progress", space.id]
      });
      setShowResync(false);
      const failed = failedNames.length;
      if (failed > 0) {
        toast.error(
          total === 1
            ? t("resync_all_wrapper_failed_one")
            : t("resync_all_wrapper_partial_failure", {
                failed,
                total,
                names:
                  failedNames.slice(0, NAMED_FAILURES).join(", ") +
                  (failedNames.length > NAMED_FAILURES ? ", …" : "")
              }),
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
          body: { name: newName.trim() }
        })
      ),
    onSuccess: () => {
      invalidate();
      setShowRename(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const deleteWrapper = useRemovalMutation({
    anchor,
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
            label: syncActive ? t("integration_sync_already_running") : t("resync_all_wrapper"),
            icon: <RefreshCw aria-hidden="true" />,
            isDisabled: syncActive,
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
      <span ref={anchor} className="contents">
        <MoreMenu
          label={t("space_more_actions_for", { name: wrapperName })}
          items={items}
          alignment="end"
        />
      </span>
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
  const formId = useId();
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
        <form
          id={formId}
          noValidate
          className="flex flex-col gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            save();
          }}
        >
          <Label htmlFor="integration-name">{t("name")}</Label>
          <Input
            ref={nameRef}
            id="integration-name"
            value={name}
            maxLength={KNOWLEDGE_NAME_MAX_LENGTH}
            onChange={(event) => onNameChange(event.target.value)}
            {...fieldProblemProps("integration-name", nameProblem)}
          />
          <FieldProblem id="integration-name" problem={nameProblem} />
        </form>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            disabled={pending}
            onClick={() => onOpenChange(false)}
          >
            {t("cancel")}
          </Button>
          {/* Never disabled: busy, it keeps focus and a second press is ignored. */}
          <Button type="submit" form={formId} aria-busy={pending || undefined}>
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
