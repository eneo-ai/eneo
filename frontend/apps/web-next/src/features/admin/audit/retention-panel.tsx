"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { retentionPolicyQueryOptions } from "./audit";

/** Audit-log retention in days (1–2555); conversation retention lives elsewhere. */
export function RetentionPanel() {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const { data: policy } = useQuery(retentionPolicyQueryOptions(browserApi));
  const [days, setDays] = useState<string | null>(null);

  const value = days ?? (policy ? String(policy.retention_days) : "");
  const dirty = policy != null && value !== String(policy.retention_days);

  const update = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.PUT("/api/v1/audit/retention-policy", {
          body: { retention_days: Number(value) }
        })
      ),
    onSuccess: (updated) => {
      queryClient.setQueryData(retentionPolicyQueryOptions(browserApi).queryKey, updated);
      setDays(null);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <div className="border-border bg-card flex flex-wrap items-end gap-4 rounded-lg border p-4">
      <div className="flex flex-col gap-1">
        <Label htmlFor="audit-retention">{t("audit_retention_policy")}</Label>
        <div className="flex items-center gap-2">
          <Input
            id="audit-retention"
            type="number"
            min={1}
            max={2555}
            className="w-32"
            value={value}
            onChange={(event) => setDays(event.target.value)}
          />
          <span className="text-muted-foreground text-sm">{t("days")}</span>
          {dirty && (
            <Button size="sm" disabled={update.isPending} onClick={() => update.mutate()}>
              {update.isPending ? t("audit_config_saving") : t("save")}
            </Button>
          )}
        </div>
      </div>
      {policy?.last_purge_at && (
        <p className="text-muted-foreground text-xs">
          {t("audit_last_purge", { count: policy.purge_count })}
        </p>
      )}
    </div>
  );
}
