"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { flushSync } from "react-dom";
import { FieldProblem, fieldProblemProps } from "@/components/composites/field-problem";
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
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import {
  SHAREPOINT_APP_KEY,
  SHAREPOINT_SUBSCRIPTIONS_KEY,
  TENANT_INTEGRATIONS_KEY
} from "./integrations";

const CONFIRM_WORD = "DELETE";

/**
 * Deleting the SharePoint app takes typing DELETE (irreversible, WCAG 3.3.4):
 * deleting without it says so at the field, which takes focus.
 */
export function SharePointAppDeleteDialog({
  open,
  onOpenChange
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [confirm, setConfirm] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const confirmRef = useRef<HTMLInputElement>(null);

  const remove = useMutation({
    mutationFn: () => unwrap(browserApi.DELETE("/api/v1/admin/sharepoint/app")),
    onSuccess: () => {
      toast.success(t("sharepoint_app_deleted_successfully"));
      for (const key of [SHAREPOINT_APP_KEY, SHAREPOINT_SUBSCRIPTIONS_KEY, TENANT_INTEGRATIONS_KEY])
        void queryClient.invalidateQueries({ queryKey: key });
      setConfirm("");
      setSubmitted(false);
      onOpenChange(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const confirmed = confirm.trim().toUpperCase() === CONFIRM_WORD;
  const problem =
    submitted && !confirmed ? t("form_problem_confirm_mismatch", { value: CONFIRM_WORD }) : null;

  function deleteApp() {
    if (remove.isPending) return;
    if (!confirmed) {
      // Rendered before focus moves, so the field is read with its error.
      flushSync(() => setSubmitted(true));
      confirmRef.current?.focus();
      return;
    }
    remove.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("delete_sharepoint_app")}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="border-destructive/30 bg-destructive/10 text-destructive flex flex-col gap-2 rounded-lg border px-3 py-2 text-sm">
            <span className="flex items-center gap-2 font-medium">
              <AlertTriangle className="size-4" /> {t("delete_sharepoint_app_warning")}
            </span>
            <ul className="ml-6 list-disc text-xs">
              <li>{t("sharepoint_delete_warning_knowledge")}</li>
              <li>{t("sharepoint_delete_warning_assistants")}</li>
              <li>{t("sharepoint_delete_warning_webhooks")}</li>
              <li>{t("sharepoint_delete_warning_tokens")}</li>
            </ul>
            <span className="font-semibold">{t("this_cannot_be_undone")}</span>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="sharepoint-app-delete-confirm">
              {t("type_to_confirm", { word: CONFIRM_WORD })}
            </Label>
            <Input
              ref={confirmRef}
              id="sharepoint-app-delete-confirm"
              value={confirm}
              autoComplete="off"
              onChange={(event) => setConfirm(event.target.value)}
              {...fieldProblemProps("sharepoint-app-delete-confirm", problem)}
            />
            <FieldProblem id="sharepoint-app-delete-confirm" problem={problem} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          {/* Never disabled: busy, it keeps focus and a second press is ignored. */}
          <Button
            variant="destructive"
            aria-busy={remove.isPending || undefined}
            onClick={deleteApp}
          >
            {remove.isPending ? t("deleting") : t("permanent_delete")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
