"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ConfirmDialog } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import { SecretRevealDialog } from "@/components/composites/secret-reveal";
import { useAppContext } from "@/components/providers/app-context";
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
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { toastApiError } from "@/lib/api/toast";
import { usePaginatedQuery } from "@/lib/hooks/use-paginated-query";

type ApiKey = Schema<"ApiKeyV2">;
type ApiKeyState = Schema<"ApiKeyState">;
type ApiKeyPermission = Schema<"ApiKeyPermission">;

const STATES: ApiKeyState[] = ["active", "suspended", "revoked", "expired"];

const STATE_BADGE_VARIANT: Record<
  ApiKeyState,
  "default" | "secondary" | "destructive" | "outline"
> = {
  active: "default",
  suspended: "secondary",
  revoked: "destructive",
  expired: "outline"
};

// Radix Select items need non-empty values; "never" encodes no expiration.
const EXPIRY_PRESETS = [
  { key: "api_keys_exp_no_expiration", value: "never" },
  { key: "api_keys_exp_30_days", value: "30" },
  { key: "api_keys_exp_90_days", value: "90" },
  { key: "api_keys_exp_1_year", value: "365" }
] as const;

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString();
}

function CreateKeyDialog({ onCreated }: { onCreated: (secret: string) => void }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [permission, setPermission] = useState<ApiKeyPermission>("read");
  const [expiryDays, setExpiryDays] = useState<string>("30");

  const createKey = useMutation({
    mutationFn: () => {
      const days = expiryDays === "never" ? null : Number(expiryDays);
      return unwrap(
        browserApi.POST("/api/v1/api-keys", {
          body: {
            name: name.trim(),
            key_type: "sk_",
            permission,
            scope_type: "tenant",
            ownership: "user",
            expires_at: days
              ? new Date(Date.now() + days * 24 * 60 * 60 * 1000).toISOString()
              : null
          }
        })
      );
    },
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
            <Select value={expiryDays} onValueChange={setExpiryDays}>
              <SelectTrigger className="w-48">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {EXPIRY_PRESETS.map((preset) => (
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

export function ApiKeys() {
  const t = useTranslations();
  const { can } = useAppContext();
  const [stateFilter, setStateFilter] = useState<ApiKeyState>("active");
  const [secret, setSecret] = useState<string | null>(null);
  const [secretTitle, setSecretTitle] = useState("");

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
      <div className="flex items-center justify-between gap-4">
        <Tabs value={stateFilter} onValueChange={(value) => setStateFilter(value as ApiKeyState)}>
          <TabsList>
            {STATES.map((state) => (
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
                <TableHead>{t("api_keys_key_type")}</TableHead>
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
                    <Badge variant={STATE_BADGE_VARIANT[apiKey.state]}>
                      {stateLabels[apiKey.state]}
                    </Badge>
                  </TableCell>
                  <TableCell className="capitalize">{apiKey.permission}</TableCell>
                  <TableCell>
                    {apiKey.expires_at ? formatDate(apiKey.expires_at) : t("api_keys_never")}
                  </TableCell>
                  <TableCell>{formatDate(apiKey.created_at)}</TableCell>
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
