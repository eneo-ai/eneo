"use client";

import { Plus, Settings, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { PageHeader } from "@/components/composites/page-header";
import { SecretRevealDialog } from "@/components/composites/secret-reveal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import {
  API_KEY_STATE_BADGE_VARIANT,
  API_KEY_STATES,
  formatApiKeyDate,
  type ApiKey,
  type ApiKeyScopeType,
  type ApiKeyState,
  type ApiKeyType
} from "@/features/api-keys/api-keys";
import { usePaginatedQuery } from "@/lib/hooks/use-paginated-query";
import { ApiKeyActions } from "@/features/api-keys/api-key-actions";
import { CreateApiKeyDialog } from "@/features/api-keys/api-key-form";
import { NotificationPolicyDialog } from "./notification-policy-dialog";
import { ApiKeyPolicyDialog } from "./policy-panel";

export function OrgApiKeysPage() {
  const t = useTranslations();
  const [state, setState] = useState<ApiKeyState>("active");
  const [scopeType, setScopeType] = useState<ApiKeyScopeType | "all">("all");
  const [keyType, setKeyType] = useState<ApiKeyType | "all">("all");
  const [secret, setSecret] = useState<string | null>(null);
  const [secretTitle, setSecretTitle] = useState("");
  const [showPolicy, setShowPolicy] = useState(false);
  const [showConstraintPolicy, setShowConstraintPolicy] = useState(false);
  const headingId = useId();

  function showSecret(title: string) {
    return (value: string) => {
      setSecretTitle(title);
      setSecret(value);
    };
  }

  const { items, hasNextPage, hasPreviousPage, nextPage, previousPage, isPending } =
    usePaginatedQuery<ApiKey>({
      queryKey: ["admin-api-keys", state, scopeType, keyType],
      fetchPage: ({ cursor, limit }) =>
        unwrap(
          browserApi.GET("/api/v1/admin/api-keys", {
            params: {
              query: {
                state,
                cursor,
                limit,
                scope_type: scopeType === "all" ? undefined : scopeType,
                key_type: keyType === "all" ? undefined : keyType
              }
            }
          })
        )
    });

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader title={t("api_keys")} headingId={headingId}>
        <Button variant="outline" onClick={() => setShowConstraintPolicy(true)}>
          <ShieldCheck className="size-4" /> {t("api_keys_admin_tenant_policy")}
        </Button>
        <Button variant="outline" onClick={() => setShowPolicy(true)}>
          <Settings className="size-4" /> {t("notification_policy")}
        </Button>
        <CreateApiKeyDialog
          idPrefix="org"
          defaultOwnership="service"
          trigger={
            <Button>
              <Plus className="size-4" /> {t("api_keys_create_short")}
            </Button>
          }
          onCreated={showSecret(t("api_keys_created_title"))}
        />
      </PageHeader>
      <NotificationPolicyDialog open={showPolicy} onOpenChange={setShowPolicy} />
      <ApiKeyPolicyDialog open={showConstraintPolicy} onOpenChange={setShowConstraintPolicy} />

      <Tabs
        value={state}
        onValueChange={(value) => setState(value as ApiKeyState)}
        className="gap-6"
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <TabsList>
            {API_KEY_STATES.map((value) => (
              <TabsTrigger key={value} value={value}>
                {t(`api_keys_status_${value}`)}
              </TabsTrigger>
            ))}
          </TabsList>
          <div className="flex flex-wrap gap-2">
            <Select
              value={scopeType}
              onValueChange={(value) => setScopeType(value as ApiKeyScopeType | "all")}
            >
              <SelectTrigger className="w-40" aria-label={t("api_keys_admin_label_scope_type")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t("api_keys_admin_scope_all")}</SelectItem>
                <SelectItem value="tenant">{t("api_keys_admin_scope_tenant")}</SelectItem>
                <SelectItem value="space">{t("api_keys_admin_scope_space")}</SelectItem>
                <SelectItem value="assistant">{t("api_keys_admin_scope_assistant")}</SelectItem>
                <SelectItem value="app">{t("api_keys_admin_scope_app")}</SelectItem>
              </SelectContent>
            </Select>
            <Select
              value={keyType}
              onValueChange={(value) => setKeyType(value as ApiKeyType | "all")}
            >
              <SelectTrigger className="w-40" aria-label={t("api_keys_admin_label_key_type")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t("api_keys_admin_key_type_all")}</SelectItem>
                <SelectItem value="pk_">{t("api_keys_admin_key_type_public")}</SelectItem>
                <SelectItem value="sk_">{t("api_keys_admin_key_type_secret")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* The keys in the selected state: the state tabs' panel. */}
        <TabsContent value={state}>
          {!isPending && items.length === 0 ? (
            <EmptyState title={t("api_keys_no_keys")} />
          ) : (
            <Table aria-labelledby={headingId}>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("name")}</TableHead>
                  <TableHead>{t("api_keys_permission_level")}</TableHead>
                  <TableHead>{t("status")}</TableHead>
                  <TableHead>{t("api_keys_expires")}</TableHead>
                  <TableHead className="w-12" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((apiKey) => (
                  <TableRow key={apiKey.id}>
                    <TableCell className="font-medium">
                      {apiKey.name}
                      <span className="text-muted-foreground ml-2 font-mono text-xs">
                        {apiKey.key_prefix}…
                      </span>
                    </TableCell>
                    <TableCell>{t(`api_keys_permission_${apiKey.permission}`)}</TableCell>
                    <TableCell>
                      <Badge variant={API_KEY_STATE_BADGE_VARIANT[apiKey.state]}>
                        {t(`api_keys_status_${apiKey.state}`)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {formatApiKeyDate(apiKey.expires_at)}
                    </TableCell>
                    <TableCell>
                      <ApiKeyActions
                        apiKey={apiKey}
                        mode="admin"
                        onRotated={showSecret(t("api_keys_rotated_title"))}
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </TabsContent>
      </Tabs>

      <div className="flex justify-end gap-2">
        <Button variant="outline" size="sm" disabled={!hasPreviousPage} onClick={previousPage}>
          {t("previous")}
        </Button>
        <Button variant="outline" size="sm" disabled={!hasNextPage} onClick={nextPage}>
          {t("next")}
        </Button>
      </div>

      <SecretRevealDialog title={secretTitle} secret={secret} onClose={() => setSecret(null)} />
    </div>
  );
}
