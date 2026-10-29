"use client";

import { Bell, BellOff, KeyRound } from "lucide-react";
import { useTranslations } from "use-intl";
import { SettingsGroup } from "@/components/composites/settings-rows";
import { useAppContext } from "@/components/providers/app-context";
import { Button } from "@/components/ui/button";
import { CreateApiKeyDialog } from "./api-key-form";
import type { ResourceScopeType } from "./api-keys";
import { useNotificationFollows } from "./notification-follows";
import { UserApiKeyList, useSecretReveal } from "./user-api-key-list";

export type ResourceApiKeyScopeType = ResourceScopeType;

/**
 * A resource's own keys (a space's, an assistant's or an app's settings):
 * create one locked to the resource, act on each through the shared actions
 * menu, and follow the resource's expiry reminders, which covers all its keys.
 */
export function ResourceApiKeysSection({
  scopeType,
  scopeId,
  resourceName
}: {
  scopeType: ResourceApiKeyScopeType;
  scopeId: string;
  resourceName: string;
}) {
  const t = useTranslations();
  const { can } = useAppContext();
  const secrets = useSecretReveal();
  const follows = useNotificationFollows();
  const scopeFollowed = follows.follows(scopeType, scopeId);

  return (
    <SettingsGroup
      title={t("api_keys")}
      description={t("api_keys_scoped_description", { resourceName })}
      headerEnd={
        <>
          <Button
            size="sm"
            variant="outline"
            aria-busy={follows.toggle.isPending || undefined}
            onClick={() => {
              if (follows.toggle.isPending) return;
              follows.toggle.mutate({
                targetType: scopeType,
                targetId: scopeId,
                follow: !scopeFollowed
              });
            }}
          >
            {scopeFollowed ? <BellOff className="size-4" /> : <Bell className="size-4" />}
            {scopeFollowed
              ? t("api_keys_notifications_unfollow_scope_action")
              : t("api_keys_notifications_follow_scope_action")}
          </Button>
          {can("api_keys") && (
            <CreateApiKeyDialog
              idPrefix={scopeType}
              lockedScope={{ type: scopeType, id: scopeId, name: resourceName }}
              trigger={
                <Button size="sm">
                  <KeyRound className="size-4" />
                  {t("api_keys_create_short")}
                </Button>
              }
              onCreated={secrets.reveal(t("api_keys_created_title"))}
            />
          )}
        </>
      }
    >
      {!can("api_keys") && (
        <p className="text-muted-foreground text-sm">{t("api_keys_no_create_permission")}</p>
      )}
      <UserApiKeyList
        scope={{ type: scopeType, id: scopeId, name: resourceName }}
        limit={10}
        onRotated={secrets.reveal(t("api_keys_rotated_title"))}
      />
      {secrets.dialog}
    </SettingsGroup>
  );
}
