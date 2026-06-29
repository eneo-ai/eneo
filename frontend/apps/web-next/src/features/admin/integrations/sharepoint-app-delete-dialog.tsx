"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import {
  SHAREPOINT_APP_KEY,
  SHAREPOINT_SUBSCRIPTIONS_KEY,
  TENANT_INTEGRATIONS_KEY
} from "./integrations";

const CONFIRM_WORD = "DELETE";

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

  const remove = useMutation({
    mutationFn: () => unwrap(browserApi.DELETE("/api/v1/admin/sharepoint/app")),
    onSuccess: () => {
      toast.success(t("sharepoint_app_deleted_successfully"));
      for (const key of [SHAREPOINT_APP_KEY, SHAREPOINT_SUBSCRIPTIONS_KEY, TENANT_INTEGRATIONS_KEY])
        void queryClient.invalidateQueries({ queryKey: key });
      setConfirm("");
      onOpenChange(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const confirmed = confirm.trim().toUpperCase() === CONFIRM_WORD;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("delete_sharepoint_app")}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
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
          <Input
            value={confirm}
            placeholder={t("type_to_confirm", { word: CONFIRM_WORD })}
            onChange={(event) => setConfirm(event.target.value)}
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            variant="destructive"
            disabled={!confirmed || remove.isPending}
            onClick={() => remove.mutate()}
          >
            {remove.isPending ? t("deleting") : t("permanent_delete")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
