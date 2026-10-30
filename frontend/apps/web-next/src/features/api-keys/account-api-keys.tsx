"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@astryxdesign/core/Button";
import { Bell } from "lucide-react";
import { useId, useState } from "react";
import { useTranslations } from "use-intl";
import { Switch } from "@/components/astryx/switch";
import { TextInput } from "@/components/astryx/text-input";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { useAutosaveField } from "@/components/composites/use-autosave";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { toastApiError } from "@/lib/api/toast";
import { CreateApiKeyDialog } from "./api-key-form";
import {
  API_KEY_NOTIFICATION_PREFERENCES_KEY,
  apiKeyNotificationPreferencesQueryOptions,
  apiKeyPolicyConstraintsQueryOptions
} from "./api-keys";
import { UserApiKeyList, useSecretReveal } from "./user-api-key-list";

function NotificationPreferencesPanel() {
  const t = useTranslations();
  const preferences = useQuery(apiKeyNotificationPreferencesQueryOptions(browserApi));
  const constraints = useQuery(apiKeyPolicyConstraintsQueryOptions(browserApi));

  return (
    <QueryStateBoundary
      queries={[preferences, constraints]}
      errorTitle={t("api_keys_notifications_settings_title")}
    >
      {() => (
        <NotificationPreferences
          preferences={preferences.data!}
          policy={constraints.data!.notification_policy}
        />
      )}
    </QueryStateBoundary>
  );
}

function reminderDays(value: string, maximum: number | null | undefined): number[] | undefined {
  const parts = value.split(",").map((part) => part.trim());
  if (parts.some((part) => !/^\d+$/.test(part))) return undefined;
  const days = parts.map(Number);
  if (
    days.some((day) => !Number.isSafeInteger(day) || day < 1 || (maximum != null && day > maximum))
  )
    return undefined;
  return [...new Set(days)].sort((a, b) => b - a);
}

function NotificationPreferences({
  preferences,
  policy
}: {
  preferences: Schema<"ApiKeyNotificationPreferencesResponse">;
  policy: Schema<"ApiKeyNotificationPolicyResponse">;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const policyHintId = useId();
  const [daysVisited, setDaysVisited] = useState(false);

  const updatePreferences = useMutation({
    // Partial preferences share one write order, including an input blur followed by a toggle.
    scope: { id: "api-key-notification-preferences" },
    mutationFn: (body: Schema<"ApiKeyNotificationPreferencesUpdate">) =>
      unwrap(browserApi.PUT("/api/v1/api-keys/notification-preferences", { body })),
    onSuccess: (updated) => {
      queryClient.setQueryData(API_KEY_NOTIFICATION_PREFERENCES_KEY, updated);
    }
  });
  const days = useAutosaveField({
    key: "api-key-reminder-days",
    value: preferences.days_before_expiry?.join(", ") ?? "",
    normalize: (value) => reminderDays(value, policy.max_days_before_expiry)?.join(", ") ?? value,
    validate: (value) => reminderDays(value, policy.max_days_before_expiry) !== undefined,
    save: (value) =>
      updatePreferences.mutateAsync({
        days_before_expiry: reminderDays(value, policy.max_days_before_expiry)!
      })
  });
  const parsedDays = reminderDays(days.value, policy.max_days_before_expiry);
  const enabled = policy.enabled !== false && (preferences.enabled ?? false);
  const saving = updatePreferences.isPending;

  function saveSwitch(body: Schema<"ApiKeyNotificationPreferencesUpdate">) {
    if (saving) return;
    updatePreferences.mutate(body, { onError: (error) => toastApiError(error, t) });
  }

  return (
    <section aria-busy={saving} className="rounded-xl border p-4">
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
            label={t("api_keys_notifications_settings_title")}
            isLabelHidden
            value={enabled}
            isDisabled={policy.enabled === false}
            disabledMessage={
              policy.enabled === false ? t("api_keys_notifications_policy_header_hint") : undefined
            }
            onChange={(checked) => saveSwitch({ enabled: checked })}
          />
        </div>
        {saving && <p className="text-ax-text-secondary text-sm">{t("saving")}</p>}
        {policy.enabled === false && (
          <p className="text-ax-text-secondary text-sm">
            {t("api_keys_notifications_policy_header_hint")}
          </p>
        )}
        {enabled && (
          <div className="grid gap-4 border-t pt-4 sm:grid-cols-3">
            <div className="flex flex-col gap-2">
              <TextInput
                label={t("api_keys_notifications_reminder_days_label")}
                description={t("api_keys_notifications_reminder_days_description")}
                value={days.value}
                onChange={days.setValue}
                isReadOnly={saving}
                aria-busy={saving}
                aria-describedby={policy.max_days_before_expiry != null ? policyHintId : undefined}
                onBlur={() => {
                  setDaysVisited(true);
                  void days.commit();
                }}
                onEnter={() => {
                  setDaysVisited(true);
                  void days.commit();
                }}
                status={
                  daysVisited && parsedDays === undefined
                    ? { type: "error", message: t("api_keys_notifications_days_validation") }
                    : undefined
                }
                statusVariant="detached"
                width="100%"
              />
              {policy.max_days_before_expiry != null && (
                <p id={policyHintId} className="text-ax-text-secondary text-sm">
                  {t("api_keys_notifications_max_days_hint", {
                    days: policy.max_days_before_expiry
                  })}
                </p>
              )}
              <div className="flex flex-wrap items-center gap-1">
                {[7, 14, 30, 60, 90]
                  .filter(
                    (day) =>
                      policy.max_days_before_expiry == null || day <= policy.max_days_before_expiry
                  )
                  .map((day) => (
                    <Button
                      key={day}
                      label={t("api_keys_notifications_add_day", { days: day })}
                      size="sm"
                      variant="ghost"
                      isDisabled={!parsedDays}
                      isLoading={saving}
                      isInterruptible
                      onClick={() => {
                        if (saving) return;
                        const value = [...new Set([...(parsedDays ?? []), day])]
                          .sort((a, b) => b - a)
                          .join(", ");
                        days.setValue(value);
                        void days.commit(value);
                      }}
                    />
                  ))}
              </div>
            </div>
            <div className="flex flex-col gap-2 rounded-lg border p-3">
              <Switch
                label={t("api_keys_notifications_auto_follow_assistants_title")}
                value={preferences.auto_follow_published_assistants ?? false}
                isDisabled={!policy.allow_auto_follow_published_assistants}
                disabledMessage={
                  !policy.allow_auto_follow_published_assistants
                    ? t("api_keys_notifications_auto_follow_assistants_locked_hint")
                    : undefined
                }
                onChange={(checked) => saveSwitch({ auto_follow_published_assistants: checked })}
              />
              {!policy.allow_auto_follow_published_assistants && (
                <p className="text-ax-text-secondary text-sm">
                  {t("api_keys_notifications_auto_follow_assistants_locked_hint")}
                </p>
              )}
            </div>
            <div className="flex flex-col gap-2 rounded-lg border p-3">
              <Switch
                label={t("api_keys_notifications_auto_follow_apps_title")}
                value={preferences.auto_follow_published_apps ?? false}
                isDisabled={!policy.allow_auto_follow_published_apps}
                disabledMessage={
                  !policy.allow_auto_follow_published_apps
                    ? t("api_keys_notifications_auto_follow_apps_locked_hint")
                    : undefined
                }
                onChange={(checked) => saveSwitch({ auto_follow_published_apps: checked })}
              />
              {!policy.allow_auto_follow_published_apps && (
                <p className="text-ax-text-secondary text-sm">
                  {t("api_keys_notifications_auto_follow_apps_locked_hint")}
                </p>
              )}
            </div>
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
              trigger={<Button label={t("api_keys_create_short")} />}
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
