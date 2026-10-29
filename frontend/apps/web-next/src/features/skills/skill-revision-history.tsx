"use client";

import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, RotateCcw } from "lucide-react";
import { useLocale, useTranslations } from "use-intl";
import { useState } from "react";
import { LoadingState } from "@/components/composites/loading-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog";
import {
  blockingError,
  ListError,
  LoadMore,
  QueryStateBoundary,
  RefreshError
} from "@/components/composites/query-state";
import { EneoApiError } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { cursorPagination, flattenPages } from "@/lib/api/pagination";
import {
  getSkillRevision,
  listSkillRevisions,
  restoreSkillRevision,
  skillQueryKey,
  type SkillScope
} from "./skill-revisions";

type Skill = Schema<"OrganizationSkillPublic"> | Schema<"SkillPublic">;
type Revision = Schema<"SkillRevisionPublic">;

function RevisionContent({ revision, current }: { revision: Revision; current: Revision }) {
  const t = useTranslations();
  return (
    <dl className="grid gap-4 sm:grid-cols-2">
      {(["display_name", "description", "instructions"] as const).map((field) => (
        <div key={field} className={field === "instructions" ? "sm:col-span-2" : ""}>
          <dt className="text-muted-foreground mb-1 flex gap-2 text-xs font-medium">
            {t(
              field === "display_name"
                ? "name"
                : field === "description"
                  ? "description"
                  : "skills_instructions_label"
            )}
            {revision[field] !== current[field] && (
              <Badge variant="outline">{t("skills_library_changed_field")}</Badge>
            )}
          </dt>
          <dd
            className={
              field === "instructions"
                ? "bg-muted/40 max-h-80 overflow-y-auto rounded-md border p-3 font-mono text-xs whitespace-pre-wrap"
                : "text-sm"
            }
          >
            {revision[field]}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function SkillRevisionHistory({
  skill,
  unsaved,
  scope,
  allowRestore = true
}: {
  skill: Skill;
  unsaved: boolean;
  scope: SkillScope;
  allowRestore?: boolean;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const queryClient = useQueryClient();
  const [viewId, setViewId] = useState<string | null>(null);
  const [restoreId, setRestoreId] = useState<string | null>(null);
  const [restoring, setRestoring] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [announcement, setAnnouncement] = useState("");
  const key = skillQueryKey(scope);
  const canRestore = allowRestore && !("removed_at" in skill && skill.removed_at);
  const revisions = useInfiniteQuery({
    queryKey: [...key, skill.id, "revisions"],
    ...cursorPagination,
    queryFn: ({ pageParam }) => listSkillRevisions(scope, skill.id, pageParam ?? null),
    retry: false
  });
  const preview = useQuery({
    queryKey: [...key, skill.id, "revision", viewId],
    enabled: Boolean(viewId) && viewId !== skill.current_revision_id,
    queryFn: () => getSkillRevision(scope, skill.id, viewId as string),
    retry: false
  });
  const revision = viewId === skill.current_revision_id ? skill.current_revision : preview.data;
  const items = flattenPages(revisions.data?.pages);

  async function restore() {
    if (!restoreId || restoring || !canRestore) return;
    setRestoring(true);
    setError(null);
    try {
      const outcome = await restoreSkillRevision(
        scope,
        skill.id,
        restoreId,
        skill.current_revision_id
      );
      setRestoreId(null);
      setViewId(null);
      setAnnouncement(
        outcome.created
          ? t("skills_library_restore_success", {
              sourceRevision: String(outcome.restored_from_revision_number),
              newRevision: String(outcome.revision.revision_number)
            })
          : t("skills_library_restore_noop")
      );
      if (outcome.created) await queryClient.invalidateQueries({ queryKey: key });
    } catch (cause) {
      setError(cause);
      if (cause instanceof EneoApiError && cause.status === 409) {
        await queryClient.invalidateQueries({ queryKey: [...key, skill.id] });
        setRestoreId(null);
      }
    } finally {
      setRestoring(false);
    }
  }

  return (
    <section className="space-y-4" aria-labelledby="organization-skill-history-heading">
      <div>
        <h2 id="organization-skill-history-heading" className="text-lg font-semibold">
          {t("skills_library_history_heading")}
        </h2>
        <p className="text-muted-foreground text-sm">{t("skills_library_history_description")}</p>
      </div>
      <p role="status" className={announcement ? "text-sm" : "sr-only"}>
        {announcement}
      </p>
      <QueryStateBoundary query={revisions} rows={3}>
        {() => (
          <>
            <div className="divide-y rounded-lg border">
              {items.map((item) => (
                <div key={item.id} className="flex flex-wrap items-center gap-3 p-3">
                  <div className="min-w-0 flex-1">
                    <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
                      {t("skills_revision_label", { revision: String(item.revision_number) })}
                      {item.id === skill.current_revision_id && (
                        <Badge variant="secondary">{t("skills_library_current_revision")}</Badge>
                      )}
                    </p>
                    <p className="text-muted-foreground truncate text-xs">
                      {item.display_name} ·{" "}
                      {new Date(item.created_at).toLocaleString(locale, {
                        dateStyle: "short",
                        timeStyle: "short"
                      })}
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    aria-label={t("skills_library_view_revision_aria", {
                      revision: String(item.revision_number)
                    })}
                    onClick={() => {
                      setError(null);
                      setViewId(item.id);
                    }}
                  >
                    <Eye className="size-4" />
                    {t("preview")}
                  </Button>
                </div>
              ))}
            </div>
            <LoadMore query={revisions} label={t("skills_library_load_older")} />
          </>
        )}
      </QueryStateBoundary>
      <Dialog
        open={viewId !== null}
        onOpenChange={(open) => {
          if (!open && !restoreId) setViewId(null);
        }}
      >
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>
              {t("skills_library_view_revision_title", {
                revision: String(revision?.revision_number ?? "")
              })}
            </DialogTitle>
          </DialogHeader>
          {blockingError(preview) ? (
            <ListError
              error={preview.error}
              title={t("skills_library_preview_error")}
              isRetrying={preview.isFetching}
              onRetry={() => void preview.refetch()}
            />
          ) : !revision ? (
            viewId !== null ? (
              <LoadingState rows={3} />
            ) : null
          ) : (
            <>
              <RefreshError queries={[preview]} />
              <RevisionContent revision={revision} current={skill.current_revision} />
              {canRestore && revision.id !== skill.current_revision_id && (
                <Button
                  className="w-fit"
                  disabled={unsaved}
                  onClick={() => {
                    setRestoreId(revision.id);
                    setViewId(null);
                  }}
                >
                  <RotateCcw className="size-4" />
                  {t("skills_library_restore_revision_from_preview")}
                </Button>
              )}
            </>
          )}
        </DialogContent>
      </Dialog>
      <AlertDialog
        open={restoreId !== null}
        onOpenChange={(open) => {
          if (!open && !restoring) setRestoreId(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("skills_library_restore_title", {
                revision: String(items.find((item) => item.id === restoreId)?.revision_number ?? "")
              })}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t("skills_library_restore_description", {
                revision: String(items.find((item) => item.id === restoreId)?.revision_number ?? "")
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {error != null && <ListError error={error} title={t("skills_library_restore_error")} />}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={restoring}>{t("cancel")}</AlertDialogCancel>
            {/* Busy, it stays enabled so it keeps focus; restore() ignores a second press. */}
            <Button
              disabled={unsaved}
              aria-busy={restoring || undefined}
              onClick={() => void restore()}
            >
              {restoring ? t("skills_library_restoring") : t("skills_library_restore_action")}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
