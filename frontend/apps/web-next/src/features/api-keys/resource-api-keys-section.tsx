"use client";

import { Bell, BellOff, KeyRound } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { SecretRevealDialog } from "@/components/composites/secret-reveal";
import { SettingsGroup } from "@/components/composites/settings-rows";
import { useAppContext } from "@/components/providers/app-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { RemovalFocusScope } from "@/features/spaces/removal";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { usePaginatedQuery } from "@/lib/hooks/use-paginated-query";
import { ApiKeyActions } from "./api-key-actions";
import { CreateApiKeyDialog } from "./api-key-form";
import {
  API_KEY_STATE_BADGE_VARIANT,
  API_KEY_STATE_FILTERS,
  API_KEYS_KEY,
  formatApiKeyDate,
  stateFilterLabelKey,
  type ApiKeyStateFilter,
  type ResourceScopeType
} from "./api-keys";
import { useNotificationFollows } from "./notification-follows";

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
  const [stateFilter, setStateFilter] = useState<ApiKeyStateFilter>("active");
  const [secret, setSecret] = useState<string | null>(null);
  const [secretTitle, setSecretTitle] = useState("");
  const panelRef = useRef<HTMLDivElement>(null);
  const follows = useNotificationFollows();
  const scopeFollowed = follows.follows(scopeType, scopeId);

  const keys = usePaginatedQuery({
    queryKey: [...API_KEYS_KEY, scopeType, scopeId, stateFilter],
    limit: 10,
    fetchPage: async ({ cursor, limit }) => {
      const page = await unwrap(
        browserApi.GET("/api/v1/api-keys", {
          params: {
            query: {
              scope_type: scopeType,
              scope_id: scopeId,
              state: stateFilter === "all" ? null : stateFilter,
              cursor: cursor ?? null,
              limit
            }
          }
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
              onCreated={showSecret(t("api_keys_created_title"))}
            />
          )}
        </>
      }
    >
      {!can("api_keys") && (
        <p className="text-muted-foreground text-sm">{t("api_keys_no_create_permission")}</p>
      )}
      <Tabs
        value={stateFilter}
        onValueChange={(value) => setStateFilter(value as ApiKeyStateFilter)}
        className="gap-6"
      >
        <TabsList>
          {API_KEY_STATE_FILTERS.map((state) => (
            <TabsTrigger key={state} value={state}>
              {t(stateFilterLabelKey(state))}
            </TabsTrigger>
          ))}
        </TabsList>

        {/* The keys in the selected state: the state tabs' panel. */}
        <TabsContent ref={panelRef} value={stateFilter} className="flex flex-col gap-4">
          <RemovalFocusScope target={panelRef}>
            {keys.items.length === 0 && !keys.isPending ? (
              <EmptyState title={t("api_keys_no_keys")} description={t("api_keys_no_keys_desc")} />
            ) : (
              <>
                <Table aria-label={t("api_keys")}>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("name")}</TableHead>
                      <TableHead>{t("status")}</TableHead>
                      <TableHead>{t("api_keys_permission_level")}</TableHead>
                      <TableHead>{t("api_keys_expires")}</TableHead>
                      <TableHead>{t("api_keys_created")}</TableHead>
                      <TableHead className="w-14 min-w-14" />
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
                            {t(`api_keys_status_${apiKey.state}`)}
                          </Badge>
                        </TableCell>
                        <TableCell>{t(`api_keys_permission_${apiKey.permission}`)}</TableCell>
                        <TableCell>
                          {apiKey.expires_at
                            ? formatApiKeyDate(apiKey.expires_at)
                            : t("api_keys_never")}
                        </TableCell>
                        <TableCell>{formatApiKeyDate(apiKey.created_at)}</TableCell>
                        <TableCell className="text-end">
                          <ApiKeyActions
                            apiKey={apiKey}
                            mode="user"
                            scopeName={resourceName}
                            followedViaScope={scopeFollowed && !follows.follows("key", apiKey.id)}
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
          </RemovalFocusScope>
        </TabsContent>
      </Tabs>

      <SecretRevealDialog title={secretTitle} secret={secret} onClose={() => setSecret(null)} />
    </SettingsGroup>
  );
}
