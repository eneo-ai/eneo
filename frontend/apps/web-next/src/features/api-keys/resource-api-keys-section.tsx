"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { KeyRound, RefreshCw, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ConfirmDialog } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import { SecretRevealDialog } from "@/components/composites/secret-reveal";
import { SettingsGroup } from "@/components/composites/settings-rows";
import { useAppContext } from "@/components/providers/app-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { usePaginatedQuery } from "@/lib/hooks/use-paginated-query";
import { CreateApiKeyForm, type ApiKeyDraft } from "./create-api-key-form";
import {
  API_KEY_STATE_BADGE_VARIANT,
  API_KEY_STATES,
  buildScopedApiKeyCreateBody,
  formatApiKeyDate,
  type ApiKey,
  type ApiKeyScopeType,
  type ApiKeyState
} from "./api-keys";

export type ResourceApiKeyScopeType = Extract<ApiKeyScopeType, "space" | "assistant" | "app">;

function CreateScopedKeyDialog({
  scopeType,
  scopeId,
  resourceName,
  onCreated
}: {
  scopeType: ResourceApiKeyScopeType;
  scopeId: string;
  resourceName: string;
  onCreated: (secret: string) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["api-keys", scopeType, scopeId] });

  const createKey = useMutation({
    mutationFn: (draft: ApiKeyDraft) =>
      unwrap(
        browserApi.POST("/api/v1/api-keys", {
          body: buildScopedApiKeyCreateBody({ ...draft, scopeType, scopeId })
        })
      ),
    onSuccess: (created) => {
      void invalidate();
      setOpen(false);
      onCreated(created.secret);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm">
          <KeyRound className="size-4" />
          {t("api_keys_create_short")}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <CreateApiKeyForm
          idPrefix={scopeType}
          title={t("api_keys_create_for_resource", { resource: resourceName })}
          pending={createKey.isPending}
          onSubmit={(draft) => createKey.mutate(draft)}
          onCancel={() => setOpen(false)}
        />
      </DialogContent>
    </Dialog>
  );
}

function ScopedKeyActions({
  apiKey,
  queryKey,
  onRotated
}: {
  apiKey: ApiKey;
  queryKey: readonly unknown[];
  onRotated: (secret: string) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey });

  const rotateKey = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/api-keys/{id}/rotate", {
          params: { path: { id: apiKey.id } },
          body: {}
        })
      ),
    onSuccess: (rotated) => {
      void invalidate();
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
    onSuccess: () => void invalidate(),
    onError: (error) => toastApiError(error, t)
  });

  if (apiKey.state !== "active") return null;

  return (
    <div className="flex justify-end gap-1">
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
  const [stateFilter, setStateFilter] = useState<ApiKeyState>("active");
  const [secret, setSecret] = useState<string | null>(null);
  const [secretTitle, setSecretTitle] = useState("");
  const queryKey = ["api-keys", scopeType, scopeId, stateFilter] as const;

  const keys = usePaginatedQuery({
    queryKey,
    limit: 10,
    fetchPage: async ({ cursor, limit }) => {
      const page = await unwrap(
        browserApi.GET("/api/v1/api-keys", {
          params: {
            query: {
              scope_type: scopeType,
              scope_id: scopeId,
              state: stateFilter,
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

  const stateLabels: Record<ApiKeyState, string> = {
    active: t("api_keys_status_active"),
    suspended: t("api_keys_status_suspended"),
    revoked: t("api_keys_status_revoked"),
    expired: t("api_keys_status_expired")
  };

  return (
    <SettingsGroup
      title={t("api_keys")}
      description={t("api_keys_scoped_description", { resourceName })}
      headerEnd={
        can("api_keys") ? (
          <CreateScopedKeyDialog
            scopeType={scopeType}
            scopeId={scopeId}
            resourceName={resourceName}
            onCreated={showSecret(t("api_keys_created_title"))}
          />
        ) : null
      }
    >
      <Tabs
        value={stateFilter}
        onValueChange={(value) => setStateFilter(value as ApiKeyState)}
        className="gap-6"
      >
        <TabsList>
          {API_KEY_STATES.map((state) => (
            <TabsTrigger key={state} value={state}>
              {stateLabels[state]}
            </TabsTrigger>
          ))}
        </TabsList>

        {/* The keys in the selected state: the state tabs' panel. */}
        <TabsContent value={stateFilter} className="flex flex-col gap-4">
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
                            {apiKey.key_prefix}...{apiKey.key_suffix}
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
                        {apiKey.expires_at
                          ? formatApiKeyDate(apiKey.expires_at)
                          : t("api_keys_never")}
                      </TableCell>
                      <TableCell>{formatApiKeyDate(apiKey.created_at)}</TableCell>
                      <TableCell>
                        <ScopedKeyActions
                          apiKey={apiKey}
                          queryKey={queryKey}
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
        </TabsContent>
      </Tabs>

      <SecretRevealDialog title={secretTitle} secret={secret} onClose={() => setSecret(null)} />
    </SettingsGroup>
  );
}
