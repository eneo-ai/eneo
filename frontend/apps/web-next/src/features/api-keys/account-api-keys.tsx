"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { useTranslations } from "next-intl";
import { useAppContext } from "@/components/providers/app-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { CreateApiKeyDialog } from "./api-key-form";
import { UserApiKeyList, useSecretReveal } from "./user-api-key-list";

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
  const { can } = useAppContext();
  const secrets = useSecretReveal();

  return (
    <div data-tour="account-api-keys" className="flex flex-col gap-4">
      <NotificationPreferencesPanel />
      <UserApiKeyList
        limit={25}
        onRotated={secrets.reveal(t("api_keys_rotated_title"))}
        toolbar={
          can("api_keys") ? (
            <CreateApiKeyDialog
              idPrefix="account"
              trigger={<Button>{t("api_keys_create_short")}</Button>}
              onCreated={secrets.reveal(t("api_keys_created_title"))}
            />
          ) : (
            <p className="text-muted-foreground text-sm">{t("api_keys_no_create_permission")}</p>
          )
        }
      />
      {secrets.dialog}
    </div>
  );
}
