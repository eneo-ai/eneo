"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import type { Schema } from "@/lib/api/models";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";

type Policy = Schema<"ApiKeyNotificationPolicyResponse">;
const POLICY_KEY = ["admin-api-key-notification-policy"];

function PolicyForm({ policy, onClose }: { policy: Policy; onClose: () => void }) {
  const t = useTranslations();
  const queryClient = useQueryClient();

  const [enabled, setEnabled] = useState(policy.enabled ?? true);
  const [defaultDays, setDefaultDays] = useState(
    (policy.default_days_before_expiry ?? []).join(", ")
  );
  const [maxDays, setMaxDays] = useState(policy.max_days_before_expiry?.toString() ?? "");
  const [followAssistants, setFollowAssistants] = useState(
    policy.allow_auto_follow_published_assistants ?? false
  );
  const [followApps, setFollowApps] = useState(policy.allow_auto_follow_published_apps ?? false);

  const save = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.PUT("/api/v1/admin/api-keys/notification-policy", {
          body: {
            enabled,
            // A list of day thresholds to notify at (e.g. "30, 7, 1").
            default_days_before_expiry: defaultDays
              .split(",")
              .map((part) => Number(part.trim()))
              .filter((n) => Number.isFinite(n) && n > 0),
            max_days_before_expiry: maxDays ? Number(maxDays) : undefined,
            allow_auto_follow_published_assistants: followAssistants,
            allow_auto_follow_published_apps: followApps
          }
        })
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: POLICY_KEY });
      toast.success(t("all_changes_saved"));
      onClose();
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <Label className="flex items-center justify-between gap-2 font-normal">
        {t("enabled")}
        <Switch checked={enabled} onCheckedChange={setEnabled} />
      </Label>
      <div className="grid grid-cols-2 gap-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="policy-default-days">{t("default_days_before_expiry")}</Label>
          <Input
            id="policy-default-days"
            type="text"
            inputMode="numeric"
            placeholder="30, 7, 1"
            value={defaultDays}
            disabled={!enabled}
            onChange={(event) => setDefaultDays(event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="policy-max-days">{t("max_days_before_expiry")}</Label>
          <Input
            id="policy-max-days"
            type="number"
            min={0}
            inputMode="numeric"
            value={maxDays}
            disabled={!enabled}
            onChange={(event) => setMaxDays(event.target.value)}
          />
        </div>
      </div>
      <Label className="flex items-center justify-between gap-2 font-normal">
        {t("allow_auto_follow_published_assistants")}
        <Switch checked={followAssistants} onCheckedChange={setFollowAssistants} />
      </Label>
      <Label className="flex items-center justify-between gap-2 font-normal">
        {t("allow_auto_follow_published_apps")}
        <Switch checked={followApps} onCheckedChange={setFollowApps} />
      </Label>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          {t("cancel")}
        </Button>
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? t("saving") : t("save")}
        </Button>
      </DialogFooter>
    </form>
  );
}

/** Tenant policy for when admins are warned about expiring org API keys. */
export function NotificationPolicyDialog({
  open,
  onOpenChange
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const { data, isPending } = useQuery({
    queryKey: POLICY_KEY,
    enabled: open,
    queryFn: () => unwrap(browserApi.GET("/api/v1/admin/api-keys/notification-policy"))
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("notification_policy")}</DialogTitle>
          <DialogDescription>{t("notification_policy_hint")}</DialogDescription>
        </DialogHeader>
        {isPending || !data ? (
          <Skeleton className="h-56 w-full" />
        ) : (
          <PolicyForm policy={data} onClose={() => onOpenChange(false)} />
        )}
      </DialogContent>
    </Dialog>
  );
}
