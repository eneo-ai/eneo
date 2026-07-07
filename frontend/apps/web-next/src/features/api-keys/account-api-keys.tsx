"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Pause, Play, RefreshCw, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ConfirmDialog } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import { SecretRevealDialog } from "@/components/composites/secret-reveal";
import { useAppContext } from "@/components/providers/app-context";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Switch } from "@/components/ui/switch";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { usePaginatedQuery } from "@/lib/hooks/use-paginated-query";
import {
  API_KEY_EXPIRY_PRESETS,
  API_KEY_STATE_BADGE_VARIANT,
  API_KEY_STATES,
  buildTenantApiKeyCreateBody,
  formatApiKeyDate,
  type ApiKey,
  type ApiKeyExpiryPresetValue,
  type ApiKeyPermission,
  type ApiKeyState
} from "./api-keys";

function CreateKeyDialog({ onCreated }: { onCreated: (secret: string) => void }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [permission, setPermission] = useState<ApiKeyPermission>("read");
  const [expiryDays, setExpiryDays] = useState<ApiKeyExpiryPresetValue>("30");

  const createKey = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/api-keys", {
          body: buildTenantApiKeyCreateBody({
            name,
            ownership: "user",
            permission,
            expiryDays
          })
        })
      ),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ["api-keys"] });
      setOpen(false);
      setName("");
      onCreated(created.secret);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>{t("api_keys_create_short")}</Button>
      </DialogTrigger>
      <DialogContent>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim()) createKey.mutate();
          }}
        >
          <DialogHeader>
            <DialogTitle>{t("api_keys_create")}</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor="key-name">{t("name")}</Label>
            <Input
              id="key-name"
              value={name}
              placeholder={t("api_keys_name_placeholder")}
              onChange={(event) => setName(event.target.value)}
              required
              autoFocus
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label>{t("api_keys_permission_level")}</Label>
            <Select
              value={permission}
              onValueChange={(next) => setPermission(next as ApiKeyPermission)}
            >
              <SelectTrigger className="w-48">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="read">{t("api_keys_permission_read")}</SelectItem>
                <SelectItem value="write">{t("api_keys_permission_write")}</SelectItem>
                <SelectItem value="admin">{t("api_keys_permission_admin")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-2">
            <Label>{t("api_keys_expiration")}</Label>
            <Select
              value={expiryDays}
              onValueChange={(value) => setExpiryDays(value as ApiKeyExpiryPresetValue)}
            >
              <SelectTrigger className="w-48">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {API_KEY_EXPIRY_PRESETS.map((preset) => (
                  <SelectItem key={preset.key} value={preset.value}>
                    {t(preset.key)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={!name.trim() || createKey.isPending}>
              {createKey.isPending ? t("api_keys_creating") : t("api_keys_create_short")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function KeyActions({
  apiKey,
  onRotated
}: {
  apiKey: ApiKey;
  onRotated: (secret: string) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["api-keys"] });

  const rotateKey = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/api-keys/{id}/rotate", {
          params: { path: { id: apiKey.id } },
          body: {}
        })
      ),
    onSuccess: (rotated) => {
      invalidate();
      onRotated(rotated.secret);
    },
    onError: (error) => toastApiError(error, t)
  });

  const revokeKey = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/api-keys/{id}/revoke", {
          params: { path: { id: apiKey.id } },
          body: {}
        })
      ),
    onSuccess: invalidate,
    onError: (error) => toastApiError(error, t)
  });

  const suspendKey = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/api-keys/{id}/suspend", {
          params: { path: { id: apiKey.id } },
          body: {}
        })
      ),
    onSuccess: invalidate,
    onError: (error) => toastApiError(error, t)
  });

  const reactivateKey = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/api-keys/{id}/reactivate", {
          params: { path: { id: apiKey.id } }
        })
      ),
    onSuccess: invalidate,
    onError: (error) => toastApiError(error, t)
  });

  return (
    <div className="flex justify-end gap-1">
      {apiKey.state === "active" && (
        <>
          <ConfirmDialog
            trigger={
              <Button variant="ghost" size="icon" aria-label={t("api_keys_action_rotate")}>
                <RefreshCw className="size-4" />
              </Button>
            }
            title={t("api_keys_rotate_confirm_title")}
            description={t("api_keys_rotate_confirm_description")}
            confirmLabel={t("api_keys_action_rotate")}
            pending={rotateKey.isPending}
            onConfirm={() => rotateKey.mutateAsync().then(() => undefined)}
          />
          <ConfirmDialog
            trigger={
              <Button variant="ghost" size="icon" aria-label={t("api_keys_action_suspend")}>
                <Pause className="size-4" />
              </Button>
            }
            title={t("api_keys_action_suspend_title")}
            description={t("api_keys_action_suspend_description")}
            confirmLabel={t("api_keys_action_suspend")}
            pending={suspendKey.isPending}
            onConfirm={() => suspendKey.mutateAsync().then(() => undefined)}
          />
        </>
      )}
      {apiKey.state === "suspended" && (
        <ConfirmDialog
          trigger={
            <Button variant="ghost" size="icon" aria-label={t("api_keys_action_reactivate")}>
              <Play className="size-4" />
            </Button>
          }
          title={t("api_keys_action_reactivate_title")}
          description={t("api_keys_action_reactivate_description")}
          confirmLabel={t("api_keys_action_reactivate")}
          pending={reactivateKey.isPending}
          onConfirm={() => reactivateKey.mutateAsync().then(() => undefined)}
        />
      )}
      <ConfirmDialog
        trigger={
          <Button variant="ghost" size="icon" aria-label={t("api_keys_action_revoke")}>
            <Trash2 className="text-destructive size-4" />
          </Button>
        }
        title={t("api_keys_action_revoke_title")}
        description={t("api_keys_action_revoke_description")}
        confirmLabel={t("api_keys_action_revoke")}
        pending={revokeKey.isPending}
        onConfirm={() => revokeKey.mutateAsync().then(() => undefined)}
      />
    </div>
  );
}

function LegacyKeyBanner({ suffix, onRevoked }: { suffix: string; onRevoked: () => void }) {
  const t = useTranslations();

  const revokeLegacy = useMutation({
    mutationFn: () => unwrap(browserApi.DELETE("/api/v1/users/api-keys/legacy")),
    onSuccess: onRevoked,
    onError: (error) => toastApiError(error, t)
  });

  return (
    <Alert>
      <AlertTitle>{t("api_keys_legacy_detected")}</AlertTitle>
      <AlertDescription>
        <p>
          {t("api_keys_legacy_ending_in")} <code>****{suffix}</code>.{" "}
          {t("api_keys_legacy_recommend")}
        </p>
        <ConfirmDialog
          trigger={
            <Button variant="outline" size="sm" className="mt-2">
              {t("api_keys_legacy_revoke")}
            </Button>
          }
          title={t("api_keys_legacy_revoke_title")}
          description={t("api_keys_legacy_revoke_description")}
          confirmLabel={t("api_keys_legacy_revoke")}
          pending={revokeLegacy.isPending}
          onConfirm={() => revokeLegacy.mutateAsync().then(() => undefined)}
        />
      </AlertDescription>
    </Alert>
  );
}

function NotificationPreferencesPanel() {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const preferences = useQuery({
    queryKey: ["api-key-notification-preferences"],
    queryFn: () => unwrap(browserApi.GET("/api/v1/api-keys/notification-preferences"))
  });

  const updatePreferences = useMutation({
    mutationFn: (body: {
      enabled?: boolean | null;
      days_before_expiry?: number[] | null;
      auto_follow_published_assistants?: boolean | null;
      auto_follow_published_apps?: boolean | null;
    }) => unwrap(browserApi.PUT("/api/v1/api-keys/notification-preferences", { body })),
    onSuccess: (updated) => {
      queryClient.setQueryData(["api-key-notification-preferences"], updated);
    },
    onError: (error) => toastApiError(error, t)
  });

  const data = preferences.data;
  const enabled = data?.enabled ?? false;
  const firstDay = data?.days_before_expiry?.[0] ?? 30;
  const disabled = preferences.isPending || updatePreferences.isPending;

  function saveDay(value: string) {
    const days = Number(value);
    if (!Number.isInteger(days) || days < 1) return;
    updatePreferences.mutate({ days_before_expiry: [days] });
  }

  return (
    <section className="rounded-xl border p-4">
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between gap-4">
          <div className="flex min-w-0 items-start gap-3">
            <Bell className="text-muted-foreground mt-0.5 size-4 shrink-0" />
            <div className="min-w-0">
              <h2 className="text-sm font-medium">{t("api_keys_notifications_settings_title")}</h2>
              <p className="text-muted-foreground text-sm">
                {t("api_keys_notifications_settings_description")}
              </p>
            </div>
          </div>
          <Switch
            checked={enabled}
            disabled={disabled}
            aria-label={t("api_keys_notifications_settings_title")}
            onCheckedChange={(checked) => updatePreferences.mutate({ enabled: checked })}
          />
        </div>
        {enabled && (
          <div className="grid gap-4 border-t pt-4 sm:grid-cols-3">
            <div className="flex flex-col gap-2">
              <Label htmlFor="api-key-notification-days">
                {t("api_keys_notifications_days_label")}
              </Label>
              <div className="flex items-center gap-2">
                <Input
                  id="api-key-notification-days"
                  type="number"
                  min={1}
                  defaultValue={firstDay}
                  disabled={disabled}
                  className="w-24"
                  onBlur={(event) => saveDay(event.target.value)}
                />
                <span className="text-muted-foreground text-sm">
                  {t("api_keys_notifications_days_unit")}
                </span>
              </div>
            </div>
            <Label className="flex items-center justify-between gap-3 rounded-lg border p-3 font-normal sm:col-span-1">
              <span className="text-sm">
                {t("api_keys_notifications_auto_follow_assistants_title")}
              </span>
              <Switch
                checked={data?.auto_follow_published_assistants ?? false}
                disabled={disabled}
                onCheckedChange={(checked) =>
                  updatePreferences.mutate({ auto_follow_published_assistants: checked })
                }
              />
            </Label>
            <Label className="flex items-center justify-between gap-3 rounded-lg border p-3 font-normal sm:col-span-1">
              <span className="text-sm">{t("api_keys_notifications_auto_follow_apps_title")}</span>
              <Switch
                checked={data?.auto_follow_published_apps ?? false}
                disabled={disabled}
                onCheckedChange={(checked) =>
                  updatePreferences.mutate({ auto_follow_published_apps: checked })
                }
              />
            </Label>
          </div>
        )}
      </div>
    </section>
  );
}

export function ApiKeys() {
  const t = useTranslations();
  const { can, user } = useAppContext();
  const [stateFilter, setStateFilter] = useState<ApiKeyState>("active");
  const [secret, setSecret] = useState<string | null>(null);
  const [secretTitle, setSecretTitle] = useState("");
  const [legacySuffix, setLegacySuffix] = useState(user.legacy_api_key_suffix ?? null);

  const keys = usePaginatedQuery({
    queryKey: ["api-keys", stateFilter],
    limit: 25,
    fetchPage: async ({ cursor, limit }) => {
      const page = await unwrap(
        browserApi.GET("/api/v1/api-keys", {
          params: { query: { state: stateFilter, cursor: cursor ?? null, limit } }
        })
      );
      return { ...page, items: page.items, total_count: page.total_count ?? 0 };
    }
  });

  function showSecret(title: string) {
    return (value: string) => {
      setSecretTitle(title);
      setSecret(value);
    };
  }

  const stateLabels: Record<ApiKeyState, string> = {
    active: t("api_keys_status_active"),
    suspended: t("api_keys_status_suspended"),
    revoked: t("api_keys_status_revoked"),
    expired: t("api_keys_status_expired")
  };

  return (
    <div className="flex flex-col gap-4">
      <NotificationPreferencesPanel />
      {legacySuffix ? (
        <LegacyKeyBanner suffix={legacySuffix} onRevoked={() => setLegacySuffix(null)} />
      ) : null}
      <div className="flex items-center justify-between gap-4">
        <Tabs value={stateFilter} onValueChange={(value) => setStateFilter(value as ApiKeyState)}>
          <TabsList>
            {API_KEY_STATES.map((state) => (
              <TabsTrigger key={state} value={state}>
                {stateLabels[state]}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        {can("api_keys") && <CreateKeyDialog onCreated={showSecret(t("api_keys_created_title"))} />}
      </div>

      {keys.items.length === 0 && !keys.isPending ? (
        <EmptyState title={t("api_keys_no_keys")} description={t("api_keys_no_keys_desc")} />
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("name")}</TableHead>
                <TableHead>{t("status")}</TableHead>
                <TableHead>{t("api_keys_permission_level")}</TableHead>
                <TableHead>{t("api_keys_expires")}</TableHead>
                <TableHead>{t("api_keys_created")}</TableHead>
                <TableHead className="w-24" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {keys.items.map((apiKey) => (
                <TableRow key={apiKey.id}>
                  <TableCell>
                    <div className="flex flex-col">
                      <span className="font-medium">{apiKey.name}</span>
                      <code className="text-muted-foreground font-mono text-xs">
                        {apiKey.key_prefix}…{apiKey.key_suffix}
                      </code>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={API_KEY_STATE_BADGE_VARIANT[apiKey.state]}>
                      {stateLabels[apiKey.state]}
                    </Badge>
                  </TableCell>
                  <TableCell>{t(`api_keys_permission_${apiKey.permission}`)}</TableCell>
                  <TableCell>
                    {apiKey.expires_at ? formatApiKeyDate(apiKey.expires_at) : t("api_keys_never")}
                  </TableCell>
                  <TableCell>{formatApiKeyDate(apiKey.created_at)}</TableCell>
                  <TableCell>
                    <KeyActions
                      apiKey={apiKey}
                      onRotated={showSecret(t("api_keys_rotated_title"))}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {(keys.hasPreviousPage || keys.hasNextPage) && (
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={!keys.hasPreviousPage}
                onClick={keys.previousPage}
              >
                {t("previous")}
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={!keys.hasNextPage}
                onClick={keys.nextPage}
              >
                {t("next")}
              </Button>
            </div>
          )}
        </>
      )}

      <SecretRevealDialog title={secretTitle} secret={secret} onClose={() => setSecret(null)} />
    </div>
  );
}
