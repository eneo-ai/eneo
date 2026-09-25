"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldAlert, ShieldCheck } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
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
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, getErrorMessage, unwrap } from "@/lib/api/errors";
import { ORGANIZATION_SKILLS_KEY } from "./organization-skills";

export function OrganizationSkillExecution({ skillId }: { skillId: string }) {
  const t = useTranslations();
  const locale = useLocale();
  const queryClient = useQueryClient();
  const [action, setAction] = useState<"block" | "unblock" | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const state = useQuery({
    queryKey: [...ORGANIZATION_SKILLS_KEY, skillId, "execution-block"],
    queryFn: () =>
      unwrap(
        browserApi.GET("/api/v1/settings/skills/{skill_id}/execution-block", {
          params: { path: { skill_id: skillId } }
        })
      ),
    retry: false
  });
  const block = state.data?.block ?? null;

  async function change() {
    if (!action || busy || !reason.trim()) return;
    setBusy(true);
    setError(null);
    try {
      let next;
      if (action === "block") {
        next = await unwrap(
          browserApi.POST("/api/v1/settings/skills/{skill_id}/execution-block", {
            params: { path: { skill_id: skillId } },
            body: { reason: reason.trim() }
          })
        );
      } else {
        if (!block) {
          await state.refetch();
          setError(t("organization_skills_execution_stale_error"));
          return;
        }
        next = await unwrap(
          browserApi.POST("/api/v1/settings/skills/{skill_id}/execution-block/unblock", {
            params: { path: { skill_id: skillId } },
            body: { expected_block_id: block.id, reason: reason.trim() }
          })
        );
      }
      queryClient.setQueryData([...ORGANIZATION_SKILLS_KEY, skillId, "execution-block"], next);
      await queryClient.invalidateQueries({
        queryKey: [...ORGANIZATION_SKILLS_KEY, skillId],
        exact: true
      });
      setAction(null);
      setReason("");
    } catch (cause) {
      setError(getErrorMessage(cause, t));
      if (cause instanceof EneoApiError && cause.code === 9052) {
        const refreshed = await state.refetch();
        if (refreshed.isError) setError(t("organization_skills_execution_refresh_error"));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-4" aria-labelledby="organization-skill-execution-heading">
      <div>
        <h2
          id="organization-skill-execution-heading"
          className="flex items-center gap-2 font-semibold"
        >
          <ShieldAlert className="size-4" />
          {t("organization_skills_execution_heading")}
        </h2>
        <p className="text-muted-foreground mt-1 text-sm">
          {t("organization_skills_execution_description")}
        </p>
      </div>
      {state.isPending ? (
        <p role="status">{t("loading")}</p>
      ) : state.isError ? (
        <Alert variant="destructive" role="alert">
          <AlertTitle>{t("request_failed")}</AlertTitle>
          <AlertDescription>
            <Button variant="outline" onClick={() => void state.refetch()}>
              {t("retry")}
            </Button>
          </AlertDescription>
        </Alert>
      ) : (
        <>
          <Badge variant={block ? "destructive" : "outline"}>
            {t(
              block
                ? "organization_skills_execution_blocked_status"
                : "organization_skills_execution_available_status"
            )}
          </Badge>
          {block && (
            <Alert variant="destructive">
              <AlertTitle>{t("organization_skills_execution_blocked_status")}</AlertTitle>
              <AlertDescription>
                <p>{t("organization_skills_execution_blocked_description")}</p>
                <p className="mt-2 font-medium">{block.reason}</p>
                <p className="mt-1 text-xs">
                  {t("organization_skills_execution_blocked_at", {
                    time: new Date(block.blocked_at).toLocaleString(locale)
                  })}
                </p>
              </AlertDescription>
            </Alert>
          )}
          <Button
            variant={block ? "outline" : "destructive"}
            onClick={() => {
              setError(null);
              setAction(block ? "unblock" : "block");
            }}
          >
            {block ? <ShieldCheck className="size-4" /> : <ShieldAlert className="size-4" />}
            {t(
              block
                ? "organization_skills_execution_unblock_action"
                : "organization_skills_execution_block_action"
            )}
          </Button>
        </>
      )}
      <AlertDialog
        open={action !== null}
        onOpenChange={(open) => {
          if (!open && !busy) {
            setAction(null);
            setReason("");
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t(
                action === "unblock"
                  ? "organization_skills_execution_unblock_title"
                  : "organization_skills_execution_block_title"
              )}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t(
                action === "unblock"
                  ? "organization_skills_execution_unblock_description"
                  : "organization_skills_execution_block_description"
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {action === "unblock" && block && (
            <div className="bg-muted/40 rounded-lg border p-3 text-sm">
              <p className="font-medium">{t("organization_skills_execution_blocked_status")}</p>
              <p>{block.reason}</p>
            </div>
          )}
          <div className="space-y-2">
            <Label htmlFor="execution-change-reason">
              {t("organization_skills_execution_reason_label")}
            </Label>
            <Textarea
              id="execution-change-reason"
              value={reason}
              maxLength={1000}
              rows={4}
              disabled={busy}
              placeholder={t("organization_skills_execution_reason_placeholder")}
              onChange={(event) => setReason(event.target.value)}
            />
            <p className="text-muted-foreground text-xs">
              {t(
                action === "unblock"
                  ? "organization_skills_execution_unblock_reason_description"
                  : "organization_skills_execution_block_reason_description"
              )}
            </p>
          </div>
          {error && (
            <Alert variant="destructive" role="alert">
              <AlertTitle>{t("organization_skills_execution_change_error_title")}</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>{t("cancel")}</AlertDialogCancel>
            <Button
              variant={action === "block" ? "destructive" : "default"}
              disabled={busy || !reason.trim() || (action === "unblock" && !block)}
              onClick={() => void change()}
            >
              {busy
                ? t("saving")
                : t(
                    action === "unblock"
                      ? "organization_skills_execution_unblock_confirm"
                      : "organization_skills_execution_block_confirm"
                  )}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
