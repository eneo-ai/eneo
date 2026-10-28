"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";
import { ClientTime, useClientTimeText } from "@/components/composites/client-time";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError } from "@/components/composites/query-state";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { browserApi } from "@/lib/api/browser";
import { toast } from "@/lib/toast";
import {
  apiKeyPolicyConstraintsQueryOptions,
  extendApiKey,
  invalidateApiKeys,
  rotateApiKey,
  withoutSecret,
  type ApiKey,
  type ApiKeyMode
} from "./api-keys";
import { ExpirationPicker } from "./expiration-picker";

/** Which key a dialog acts on: its name and its visible prefix and suffix. */
export function KeyCard({ apiKey }: { apiKey: ApiKey }) {
  return (
    <div className="bg-muted rounded-lg border p-3">
      <p className="text-sm font-medium">{apiKey.name}</p>
      <p className="text-muted-foreground mt-0.5 font-mono text-xs">
        {apiKey.key_prefix}…{apiKey.key_suffix}
      </p>
    </div>
  );
}

type KeyDialogProps = {
  apiKey: ApiKey;
  mode: ApiKeyMode;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

/**
 * Rotates a key: a new secret, while the current one keeps working for the
 * policy's grace period (or stops at once, when the user says so), optionally
 * with a new expiry. The new secret goes to `onRotated` for the one-time
 * reveal and is kept nowhere else.
 */
export function RotateApiKeyDialog({
  onRotated,
  ...props
}: KeyDialogProps & { onRotated: (secret: string) => void }) {
  const t = useTranslations();
  return (
    <Dialog open={props.open} onOpenChange={props.onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("api_keys_rotate_confirm_title")}</DialogTitle>
          <DialogDescription>{t("api_keys_rotate_confirm_description")}</DialogDescription>
        </DialogHeader>
        {/* Mounted while open: each opening starts from the key as it is. */}
        <RotateBody {...props} onRotated={onRotated} />
      </DialogContent>
    </Dialog>
  );
}

function RotateBody({
  apiKey,
  mode,
  open,
  onOpenChange,
  onRotated
}: KeyDialogProps & { onRotated: (secret: string) => void }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const id = useId();
  const constraints = useQuery({
    ...apiKeyPolicyConstraintsQueryOptions(browserApi),
    enabled: open
  });
  const [disableGrace, setDisableGrace] = useState(false);
  const [alsoExtend, setAlsoExtend] = useState(false);
  const [expiresAt, setExpiresAt] = useState(apiKey.expires_at ?? null);
  const secret = useRef<string | null>(null);
  const graceHours = constraints.data?.rotation_grace_hours ?? 24;

  const rotate = useMutation({
    mutationFn: () =>
      withoutSecret(
        rotateApiKey(browserApi, mode, apiKey.id, {
          ...(alsoExtend ? { update_expiration: true, expires_at: expiresAt } : {}),
          ...(disableGrace ? { disable_grace_period: true } : {})
        }),
        (value) => {
          secret.current = value;
        }
      ),
    onSuccess: () => {
      void invalidateApiKeys(queryClient);
      onOpenChange(false);
      if (secret.current) onRotated(secret.current);
      secret.current = null;
    }
  });

  return (
    <>
      {constraints.isPending ? (
        <LoadingState rows={3} />
      ) : (
        <div className="flex flex-col gap-4">
          <KeyCard apiKey={apiKey} />
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
            <dt className="text-muted-foreground">{t("api_keys_rotate_grace_period_label")}</dt>
            <dd className="font-medium">
              {disableGrace
                ? t("api_keys_rotate_grace_period_disabled_value")
                : t("api_keys_rotate_grace_period_value", { hours: graceHours })}
            </dd>
            {apiKey.last_used_at && (
              <>
                <dt className="text-muted-foreground">{t("api_keys_rotate_last_used_label")}</dt>
                <dd>
                  <ClientTime value={apiKey.last_used_at} format="relative" />
                </dd>
              </>
            )}
            {apiKey.expires_at && (
              <>
                <dt className="text-muted-foreground">{t("api_keys_rotate_expires_label")}</dt>
                <dd>
                  <ClientTime value={apiKey.expires_at} format="date" />
                </dd>
              </>
            )}
          </dl>
          <Alert variant={disableGrace ? "destructive" : "default"}>
            <AlertDescription>
              {disableGrace
                ? t("api_keys_rotate_disable_grace_warning")
                : t("api_keys_rotate_grace_info", { hours: graceHours })}
            </AlertDescription>
          </Alert>
          <div className="flex items-start gap-2">
            <Checkbox
              id={`${id}-grace`}
              className="mt-0.5"
              checked={disableGrace}
              onCheckedChange={(checked) => setDisableGrace(checked === true)}
              aria-describedby={`${id}-grace-help`}
            />
            <div className="flex flex-col gap-0.5">
              <Label htmlFor={`${id}-grace`}>{t("api_keys_rotate_disable_grace_label")}</Label>
              <span id={`${id}-grace-help`} className="text-muted-foreground text-xs">
                {t("api_keys_rotate_disable_grace_help")}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Checkbox
              id={`${id}-extend`}
              checked={alsoExtend}
              onCheckedChange={(checked) => setAlsoExtend(checked === true)}
            />
            <Label htmlFor={`${id}-extend`}>{t("api_keys_rotate_also_extend_label")}</Label>
          </div>
          {alsoExtend && (
            <ExpirationPicker
              id={`${id}-expiry`}
              value={expiresAt}
              onChange={setExpiresAt}
              maxDays={constraints.data?.max_expiration_days}
              required={constraints.data?.require_expiration ?? false}
            />
          )}
          {rotate.error != null && <ListError error={rotate.error} compact />}
        </div>
      )}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
          {t("cancel")}
        </Button>
        {/* Never disabled: busy, it keeps focus and a second press is ignored. */}
        <Button
          aria-busy={rotate.isPending || undefined}
          onClick={() => {
            if (!rotate.isPending && !constraints.isPending) rotate.mutate();
          }}
        >
          {mode === "admin" ? t("api_keys_admin_action_rotate") : t("api_keys_action_rotate")}
        </Button>
      </DialogFooter>
    </>
  );
}

/**
 * Changes when a key expires (later, sooner, or never where the policy
 * allows), with the current and the new expiry side by side. A refusal (a
 * policy violation) shows in the dialog, which stays open.
 */
export function ExtendExpirationDialog(props: KeyDialogProps) {
  const t = useTranslations();
  return (
    <Dialog open={props.open} onOpenChange={props.onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("api_keys_extend_dialog_title")}</DialogTitle>
          <DialogDescription>{t("api_keys_extend_dialog_description")}</DialogDescription>
        </DialogHeader>
        <ExtendBody {...props} />
      </DialogContent>
    </Dialog>
  );
}

function ExtendBody({ apiKey, mode, open, onOpenChange }: KeyDialogProps) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const id = useId();
  const constraints = useQuery({
    ...apiKeyPolicyConstraintsQueryOptions(browserApi),
    enabled: open
  });
  const current = apiKey.expires_at ?? null;
  const [expiresAt, setExpiresAt] = useState(current);
  const changed = expiresAt !== current;
  const currentText = useClientTimeText(current, "date_time");
  const nextText = useClientTimeText(expiresAt, "date_time");

  const extend = useMutation({
    mutationFn: () => extendApiKey(browserApi, mode, apiKey.id, expiresAt),
    onSuccess: () => {
      void invalidateApiKeys(queryClient);
      onOpenChange(false);
      toast.success(t("api_keys_extend_saved"));
    }
  });

  return (
    <>
      {constraints.isPending ? (
        <LoadingState rows={3} />
      ) : (
        <div className="flex flex-col gap-4">
          <KeyCard apiKey={apiKey} />
          <dl className="grid gap-3 rounded-lg border p-3 sm:grid-cols-2">
            <div>
              <dt className="text-muted-foreground text-xs">
                {t("api_keys_extend_summary_previous")}
              </dt>
              <dd className="text-sm font-medium">
                {current ? currentText : t("api_keys_extend_summary_no_expiration")}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground text-xs">{t("api_keys_extend_summary_new")}</dt>
              <dd className="text-sm font-medium">
                {expiresAt ? nextText : t("api_keys_extend_summary_no_expiration")}
              </dd>
            </div>
          </dl>
          <ExpirationPicker
            id={`${id}-expiry`}
            value={expiresAt}
            onChange={setExpiresAt}
            maxDays={constraints.data?.max_expiration_days}
            required={constraints.data?.require_expiration ?? false}
          />
          {!changed && (
            <p className="text-muted-foreground text-xs">{t("api_keys_extend_no_change_hint")}</p>
          )}
          {extend.error != null && <ListError error={extend.error} compact />}
        </div>
      )}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
          {t("cancel")}
        </Button>
        {/* Never disabled: unchanged it just closes; busy, a second press is ignored. */}
        <Button
          aria-busy={extend.isPending || undefined}
          onClick={() => {
            if (extend.isPending || constraints.isPending) return;
            if (changed) extend.mutate();
            else onOpenChange(false);
          }}
        >
          {t("api_keys_extend_apply")}
        </Button>
      </DialogFooter>
    </>
  );
}
