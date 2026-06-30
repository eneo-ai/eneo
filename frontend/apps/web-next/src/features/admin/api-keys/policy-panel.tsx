"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { toastApiError } from "@/lib/api/toast";

type Policy = Schema<"ApiKeyPolicyResponse">;
type PolicyUpdate = Schema<"ApiKeyPolicyUpdate">;
type SuperKeyStatus = Schema<"SuperApiKeyStatus">;

const POLICY_KEY = ["admin-api-key-policy"];
const SUPER_KEY = ["admin-super-api-key-status"];

/** Editable per-tenant API-key policy + read-only super-key env status. */
export function ApiKeyPolicyDialog({
  open,
  onOpenChange
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();

  const { data: policy, isPending } = useQuery({
    queryKey: POLICY_KEY,
    enabled: open,
    queryFn: () => unwrap(browserApi.GET("/api/v1/admin/api-key-policy"))
  });

  const { data: superStatus } = useQuery({
    queryKey: SUPER_KEY,
    enabled: open,
    queryFn: () => unwrap(browserApi.GET("/api/v1/admin/super-api-key-status"))
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t("api_keys_admin_tenant_policy")}</DialogTitle>
          <DialogDescription>{t("api_keys_admin_policy_description")}</DialogDescription>
        </DialogHeader>

        {isPending || !policy ? (
          <Skeleton className="h-72 w-full" />
        ) : (
          <PolicyForm
            policy={policy}
            superStatus={superStatus}
            onClose={() => onOpenChange(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function PolicyForm({
  policy,
  superStatus,
  onClose
}: {
  policy: Policy;
  superStatus: SuperKeyStatus | undefined;
  onClose: () => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Policy>(policy);

  const save = useMutation({
    mutationFn: () => {
      // ApiKeyPolicyUpdate is extra="forbid" — send only changed fields.
      const body: PolicyUpdate = {};
      if (draft.require_expiration !== policy.require_expiration) {
        body.require_expiration = draft.require_expiration ?? null;
      }
      if (draft.max_expiration_days !== policy.max_expiration_days) {
        body.max_expiration_days = draft.max_expiration_days ?? null;
      }
      if (draft.auto_expire_unused_days !== policy.auto_expire_unused_days) {
        body.auto_expire_unused_days = draft.auto_expire_unused_days ?? null;
      }
      if (draft.max_rate_limit_override !== policy.max_rate_limit_override) {
        body.max_rate_limit_override = draft.max_rate_limit_override ?? null;
      }
      if (draft.rotation_grace_hours !== policy.rotation_grace_hours) {
        body.rotation_grace_hours = draft.rotation_grace_hours ?? null;
      }
      if (draft.max_delegation_depth !== policy.max_delegation_depth) {
        body.max_delegation_depth = draft.max_delegation_depth ?? null;
      }
      if (draft.revocation_cascade_enabled !== policy.revocation_cascade_enabled) {
        body.revocation_cascade_enabled = draft.revocation_cascade_enabled ?? null;
      }
      return unwrap(browserApi.PATCH("/api/v1/admin/api-key-policy", { body }));
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: POLICY_KEY });
      onClose();
    },
    onError: (error) => toastApiError(error, t)
  });

  const dirty = (Object.keys(draft) as (keyof Policy)[]).some((key) => draft[key] !== policy[key]);

  const setField = (key: keyof PolicyUpdate, value: number | boolean | null) =>
    setDraft((prev) => ({ ...prev, [key]: value }));

  const numberValue = (value: number | null | undefined) =>
    value === null || value === undefined ? "" : String(value);
  const onNumber =
    (key: keyof PolicyUpdate, min: number) => (event: React.ChangeEvent<HTMLInputElement>) => {
      const raw = event.target.value.trim();
      if (raw === "") {
        setField(key, null);
        return;
      }
      const value = Number(raw);
      if (!Number.isFinite(value) || value < min) return;
      setField(key, value);
    };

  return (
    <>
      <div className="flex flex-col gap-4">
        <ToggleRow
          label={t("api_keys_admin_policy_require_expiration")}
          description={t("api_keys_admin_policy_require_expiration_desc")}
          checked={draft.require_expiration ?? false}
          onCheckedChange={(value) => setField("require_expiration", value)}
        />
        <NumberRow
          label={t("api_keys_admin_policy_max_expiration")}
          description={t("api_keys_admin_policy_max_expiration_desc")}
          placeholder={t("api_keys_admin_policy_placeholder_no_limit")}
          suffix={t("api_keys_admin_policy_suffix_days")}
          min={1}
          value={numberValue(draft.max_expiration_days)}
          onChange={onNumber("max_expiration_days", 1)}
        />
        <NumberRow
          label={t("api_keys_admin_policy_auto_expire")}
          description={t("api_keys_admin_policy_auto_expire_desc")}
          placeholder={t("api_keys_admin_policy_placeholder_disabled")}
          suffix={t("api_keys_admin_policy_suffix_days")}
          min={1}
          value={numberValue(draft.auto_expire_unused_days)}
          onChange={onNumber("auto_expire_unused_days", 1)}
        />
        <NumberRow
          label={t("api_keys_admin_policy_max_rate_limit")}
          description={t("api_keys_admin_policy_max_rate_limit_desc")}
          placeholder={t("api_keys_admin_policy_placeholder_no_limit")}
          suffix={t("api_keys_admin_policy_suffix_req_hr")}
          min={1}
          value={numberValue(draft.max_rate_limit_override)}
          onChange={onNumber("max_rate_limit_override", 1)}
        />
        <NumberRow
          label={t("api_keys_admin_policy_rotation_grace")}
          description={t("api_keys_admin_policy_rotation_grace_desc")}
          placeholder="24"
          suffix={t("api_keys_admin_policy_suffix_hours")}
          min={0}
          value={numberValue(draft.rotation_grace_hours)}
          onChange={onNumber("rotation_grace_hours", 0)}
        />
        <NumberRow
          label={t("api_keys_admin_policy_max_delegation")}
          description={t("api_keys_admin_policy_max_delegation_desc")}
          placeholder={t("api_keys_admin_policy_placeholder_no_limit")}
          suffix={t("api_keys_admin_policy_suffix_levels")}
          min={1}
          value={numberValue(draft.max_delegation_depth)}
          onChange={onNumber("max_delegation_depth", 1)}
        />
        <ToggleRow
          label={t("api_keys_admin_policy_revocation_cascade")}
          description={t("api_keys_admin_policy_revocation_cascade_desc")}
          checked={draft.revocation_cascade_enabled ?? false}
          onCheckedChange={(value) => setField("revocation_cascade_enabled", value)}
        />

        <SuperKeySection status={superStatus} t={t} />
      </div>

      <DialogFooter>
        <span className="text-muted-foreground mr-auto text-xs">
          {dirty ? t("api_keys_admin_changes_apply") : ""}
        </span>
        <Button variant="outline" onClick={onClose}>
          {t("cancel")}
        </Button>
        <Button disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
          {t("api_keys_admin_save_changes")}
        </Button>
      </DialogFooter>
    </>
  );
}

function ToggleRow({
  label,
  description,
  checked,
  onCheckedChange
}: {
  label: string;
  description: string;
  checked: boolean;
  onCheckedChange: (value: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-lg border p-3">
      <div className="flex flex-col gap-0.5">
        <span className="text-sm font-medium">{label}</span>
        <span className="text-muted-foreground text-xs">{description}</span>
      </div>
      <Switch checked={checked} onCheckedChange={onCheckedChange} aria-label={label} />
    </div>
  );
}

function NumberRow({
  label,
  description,
  placeholder,
  suffix,
  min,
  value,
  onChange
}: {
  label: string;
  description: string;
  placeholder: string;
  suffix: string;
  min: number;
  value: string;
  onChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-lg border p-3">
      <div className="flex flex-col gap-0.5">
        <Label className="text-sm font-medium">{label}</Label>
        <span className="text-muted-foreground text-xs">{description}</span>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Input
          type="number"
          min={min}
          className="w-24"
          placeholder={placeholder}
          value={value}
          onChange={onChange}
        />
        <span className="text-muted-foreground text-xs">{suffix}</span>
      </div>
    </div>
  );
}

function SuperKeySection({
  status,
  t
}: {
  status: SuperKeyStatus | undefined;
  t: ReturnType<typeof useTranslations>;
}) {
  const rows: { env: string; configured: boolean; legacy: boolean }[] = status
    ? [
        {
          env: "ENEO_SUPER_API_KEY",
          configured: status.super_api_key_configured,
          legacy: status.super_api_key_using_legacy ?? false
        },
        {
          env: "ENEO_SUPER_DUPER_API_KEY",
          configured: status.super_duper_api_key_configured,
          legacy: status.super_duper_api_key_using_legacy ?? false
        }
      ]
    : [];

  return (
    <div className="mt-2 flex flex-col gap-3 rounded-lg border p-3">
      <div className="flex flex-col gap-0.5">
        <span className="text-sm font-medium">{t("api_keys_admin_super_key_status")}</span>
        <span className="text-muted-foreground text-xs">
          {t("api_keys_admin_super_key_description")}
        </span>
      </div>
      {!status ? (
        <Skeleton className="h-12 w-full" />
      ) : (
        <div className="flex flex-col gap-2">
          {rows.map((row) => (
            <div key={row.env} className="flex flex-col gap-0.5">
              <div className="flex items-center justify-between gap-2">
                <code className="text-xs">{row.env}</code>
                <Badge variant={row.configured ? "default" : "destructive"}>
                  {row.configured
                    ? t("api_keys_admin_status_configured")
                    : t("api_keys_admin_status_not_configured")}
                </Badge>
              </div>
              {row.legacy && (
                <span className="text-muted-foreground text-xs italic">
                  {t("api_keys_admin_status_using_legacy", { newVar: row.env })}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
      <p className="text-muted-foreground text-xs">{t("api_keys_admin_super_keys_info")}</p>
    </div>
  );
}
