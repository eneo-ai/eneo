"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/api/browser";
import { getErrorMessage, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { ORGANIZATION_SKILLS_KEY } from "./organization-skills";
import {
  advancePublishedBindings,
  initialRollout,
  type RolloutProgress,
  type RolloutScope
} from "./skill-rollout";

type Skill = Schema<"OrganizationSkillPublic">;
type Adoption = Schema<"SkillAdoptionProjectionPagePublic">;

export function OrganizationSkillPublication({
  skill,
  unsaved
}: {
  skill: Skill;
  unsaved: boolean;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const stop = useRef(false);
  const [action, setAction] = useState<"publish" | "unpublish" | null>(null);
  const [includeAssistants, setIncludeAssistants] = useState(true);
  const [includeApps, setIncludeApps] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rollout, setRollout] = useState<RolloutProgress | null>(null);
  const [rolloutScope, setRolloutScope] = useState<RolloutScope | null>(null);
  const [rolloutRevisionId, setRolloutRevisionId] = useState<string | null>(null);
  const published = useQuery({
    queryKey: [...ORGANIZATION_SKILLS_KEY, skill.id, "published"],
    enabled: skill.published_revision_number !== null,
    queryFn: () =>
      unwrap(
        browserApi.GET("/api/v1/skills/catalogue/{skill_id}/", {
          params: { path: { skill_id: skill.id } }
        })
      ),
    retry: false
  });
  const adoption = useQuery({
    queryKey: [...ORGANIZATION_SKILLS_KEY, skill.id, "adoption-summary"],
    queryFn: () =>
      unwrap(
        browserApi.GET("/api/v1/skills/organization/{skill_id}/adoption/", {
          params: { path: { skill_id: skill.id }, query: { limit: 1 } }
        })
      ),
    retry: false
  });

  useEffect(
    () => () => {
      stop.current = true;
    },
    []
  );

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ORGANIZATION_SKILLS_KEY });
  }

  async function beginRollout(revisionId: string, scope: RolloutScope, reviewed: Adoption | null) {
    stop.current = false;
    setRolloutScope(scope);
    setRolloutRevisionId(revisionId);
    setRollout(initialRollout(scope, reviewed, revisionId));
    await advancePublishedBindings({
      skillId: skill.id,
      revisionId,
      adoption: reviewed,
      scope,
      stopped: () => stop.current,
      onProgress: (update) =>
        setRollout(
          (current) =>
            current && {
              ...current,
              ...update,
              assistants: current.assistants + (update.assistants ?? 0),
              apps: current.apps + (update.apps ?? 0),
              incompatible: current.incompatible + (update.incompatible ?? 0),
              concurrent: current.concurrent + (update.concurrent ?? 0)
            }
        )
    });
    await refresh();
  }

  async function changePublication() {
    if (!action || busy || unsaved || rollout?.status === "running") return;
    setBusy(true);
    setError(null);
    const selectedAction = action;
    const scope = { assistants: includeAssistants, apps: includeApps };
    let reviewed: Adoption | null = null;
    if (selectedAction === "publish" && (scope.assistants || scope.apps)) {
      const current = await adoption.refetch();
      reviewed = current.data ?? null;
    }
    try {
      const next =
        selectedAction === "publish"
          ? await unwrap(
              browserApi.POST("/api/v1/skills/organization/{skill_id}/publish/", {
                params: { path: { skill_id: skill.id } },
                body: { expected_revision_id: skill.current_revision_id }
              })
            )
          : await unwrap(
              browserApi.POST("/api/v1/skills/organization/{skill_id}/unpublish/", {
                params: { path: { skill_id: skill.id } }
              })
            );
      queryClient.setQueryData([...ORGANIZATION_SKILLS_KEY, skill.id], next);
      setAction(null);
      setBusy(false);
      if (selectedAction === "publish" && (scope.assistants || scope.apps))
        await beginRollout(next.current_revision_id, scope, reviewed);
      else {
        setRollout(null);
        setRolloutScope(null);
        setRolloutRevisionId(null);
        await refresh();
      }
    } catch (cause) {
      setError(getErrorMessage(cause, t));
      setBusy(false);
    }
  }

  async function retryRollout() {
    const currentPublishedRevisionId =
      skill.published_revision_number === skill.current_revision_number
        ? skill.current_revision_id
        : published.data?.revision_id;
    const revisionId = currentPublishedRevisionId ?? rolloutRevisionId;
    const scope = rolloutScope ?? { assistants: true, apps: true };
    if (!revisionId || rollout?.status === "running" || busy) return;
    setBusy(true);
    try {
      const reviewed = await adoption.refetch();
      await beginRollout(revisionId, scope, reviewed.data ?? null);
    } finally {
      setBusy(false);
    }
  }

  const status = skill.publication_state;
  const canPublish = status !== "published";
  const canUnpublish = status === "published" || status === "update_pending";
  const unavailable = unsaved || rollout?.status === "running";

  return (
    <section className="space-y-4" aria-labelledby="organization-skill-publication-heading">
      <div>
        <h2 id="organization-skill-publication-heading" className="font-semibold">
          {t("organization_skills_publication_heading")}
        </h2>
        <p className="text-muted-foreground mt-1 text-sm">
          {t("organization_skills_publication_description")}
        </p>
      </div>
      <Badge variant={status === "published" ? "secondary" : "outline"}>
        {t(`organization_skills_status_${status}`)}
      </Badge>
      <dl className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <dt className="text-muted-foreground">
            {t("organization_skills_current_revision_label")}
          </dt>
          <dd>
            {t("organization_skills_version", { version: String(skill.current_revision_number) })}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">
            {t("organization_skills_approved_revision_label")}
          </dt>
          <dd>
            {skill.published_revision_number === null
              ? t("organization_skills_not_published")
              : t("organization_skills_version", {
                  version: String(skill.published_revision_number)
                })}
          </dd>
        </div>
      </dl>
      {status === "update_pending" && (
        <Alert role="note">
          <AlertTitle>{t("organization_skills_update_pending_title")}</AlertTitle>
          <AlertDescription>{t("organization_skills_update_pending_description")}</AlertDescription>
        </Alert>
      )}
      <div className="flex flex-wrap gap-2">
        {canPublish && (
          <Button
            disabled={unavailable}
            onClick={() => {
              setError(null);
              setAction("publish");
            }}
          >
            {t(
              status === "update_pending"
                ? "organization_skills_publish_update_action"
                : "organization_skills_publish_action"
            )}
          </Button>
        )}
        {canUnpublish && (
          <Button
            variant="outline"
            disabled={unavailable}
            onClick={() => {
              setError(null);
              setAction("unpublish");
            }}
          >
            {t("organization_skills_unpublish_action")}
          </Button>
        )}
      </div>
      {unsaved && (
        <p className="text-muted-foreground text-xs">
          {t("organization_skills_save_before_publication")}
        </p>
      )}
      {skill.published_revision_number !== null &&
        skill.published_revision_number !== skill.current_revision_number &&
        published.data && (
          <div className="space-y-2 rounded-lg border p-4">
            <h3 className="text-sm font-semibold">
              {t("organization_skills_approved_snapshot_heading")}
            </h3>
            <p className="text-muted-foreground text-sm">
              {t("organization_skills_approved_snapshot_description")}
            </p>
            <p className="text-sm font-medium">{published.data.revision.display_name}</p>
            <pre className="bg-muted/40 max-h-56 overflow-y-auto rounded-md p-3 font-mono text-xs whitespace-pre-wrap">
              {published.data.revision.instructions}
            </pre>
          </div>
        )}
      {rollout && (
        <div className="space-y-3 rounded-lg border p-4" role="status">
          <h3 className="font-medium">{t("organization_skills_rollout_title")}</h3>
          <Badge variant={rollout.status === "failed" ? "destructive" : "outline"}>
            {t(`organization_skills_rollout_status_${rollout.status}`)}
          </Badge>
          <dl className="grid grid-cols-2 gap-2 text-sm">
            <div>
              <dt>{t("assistants")}</dt>
              <dd>{rollout.assistants}</dd>
            </div>
            <div>
              <dt>{t("apps")}</dt>
              <dd>{rollout.apps}</dd>
            </div>
            <div>
              <dt>{t("organization_skills_rollout_concurrent_change")}</dt>
              <dd>{rollout.concurrent}</dd>
            </div>
            <div>
              <dt>{t("organization_skills_rollout_context_window")}</dt>
              <dd>{rollout.incompatible}</dd>
            </div>
          </dl>
          <p className="text-muted-foreground text-xs">
            {t(`organization_skills_rollout_personal_chat_${rollout.personalChat}`)}
          </p>
          {rollout.status === "running" ? (
            <Button
              variant="outline"
              onClick={() => {
                stop.current = true;
              }}
            >
              {t("organization_skills_rollout_stop")}
            </Button>
          ) : rollout.status === "failed" || rollout.status === "stopped" ? (
            <Button variant="outline" disabled={busy} onClick={() => void retryRollout()}>
              {t("organization_skills_rollout_restart")}
            </Button>
          ) : null}
        </div>
      )}
      {skill.published_revision_number !== null &&
        !skill.execution_blocked &&
        adoption.data?.summary &&
        adoption.data.summary.behind_published_count > 0 &&
        rollout?.status !== "running" && (
          <Alert role="note">
            <AlertTitle>{t("organization_skills_rollout_recovery_title")}</AlertTitle>
            <AlertDescription>
              <p>{t("organization_skills_rollout_recovery_description")}</p>
              <Button
                className="mt-3"
                variant="outline"
                disabled={busy}
                onClick={() => void retryRollout()}
              >
                {t("organization_skills_rollout_recovery_action")}
              </Button>
            </AlertDescription>
          </Alert>
        )}
      <AlertDialog
        open={action !== null}
        onOpenChange={(open) => {
          if (!open && !busy) setAction(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t(
                action === "unpublish"
                  ? "organization_skills_unpublish_title"
                  : "organization_skills_publish_title"
              )}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {action === "unpublish"
                ? t("organization_skills_unpublish_description")
                : t("organization_skills_publish_description", {
                    revision: String(skill.current_revision_number)
                  })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {action === "publish" && (
            <div className="space-y-4">
              <label className="flex items-start gap-2">
                <input
                  type="checkbox"
                  className="accent-primary mt-1 size-4"
                  checked={includeAssistants}
                  disabled={busy}
                  onChange={(event) => setIncludeAssistants(event.target.checked)}
                />
                <span>
                  <span className="block text-sm font-medium">
                    {t("organization_skills_publish_update_bindings_label")}
                  </span>
                  <span className="text-muted-foreground text-xs">
                    {t("organization_skills_publish_update_bindings_description")}
                  </span>
                </span>
              </label>
              <label className="flex items-start gap-2">
                <input
                  type="checkbox"
                  className="accent-primary mt-1 size-4"
                  checked={includeApps}
                  disabled={busy}
                  onChange={(event) => setIncludeApps(event.target.checked)}
                />
                <span>
                  <span className="block text-sm font-medium">
                    {t("organization_skills_publish_update_apps_label")}
                  </span>
                  <span className="text-muted-foreground text-xs">
                    {t("organization_skills_publish_update_apps_description")}
                  </span>
                </span>
              </label>
            </div>
          )}
          {error && (
            <Alert variant="destructive" role="alert">
              <AlertTitle>{t("organization_skills_publication_error_title")}</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>{t("cancel")}</AlertDialogCancel>
            <Button
              variant={action === "unpublish" ? "destructive" : "default"}
              disabled={busy}
              onClick={() => void changePublication()}
            >
              {busy
                ? t("saving")
                : t(
                    action === "unpublish"
                      ? "organization_skills_unpublish_action"
                      : "organization_skills_publish_action"
                  )}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
