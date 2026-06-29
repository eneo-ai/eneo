"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
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
import { Skeleton } from "@/components/ui/skeleton";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { SHAREPOINT_APP_KEY, sharepointAppQueryOptions } from "./integrations";

type AuthMethod = "service_account" | "tenant_app";
const OAUTH_STATE_KEY = "sharepoint_service_account_oauth";

export function SharePointAppConfigDialog({
  open,
  onOpenChange,
  onRequestDelete
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onRequestDelete: () => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const { data: config, isPending } = useQuery({
    ...sharepointAppQueryOptions(browserApi),
    enabled: open
  });

  const [authMethod, setAuthMethod] = useState<AuthMethod>("service_account");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [tenantDomain, setTenantDomain] = useState("");
  const [updatingSecret, setUpdatingSecret] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message?: string } | null>(null);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: SHAREPOINT_APP_KEY });
  const requireFields = () => {
    if (!clientId.trim() || !clientSecret.trim() || !tenantDomain.trim()) {
      toast.warning(t("fill_required_fields"));
      return false;
    }
    return true;
  };

  const test = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/admin/sharepoint/app/test", {
          body: {
            client_id: clientId.trim(),
            client_secret: clientSecret,
            tenant_domain: tenantDomain.trim()
          }
        })
      ),
    onSuccess: (result) =>
      setTestResult({ ok: result.success, message: result.error_message ?? result.details ?? "" }),
    onError: (error) => toastApiError(error, t)
  });

  const save = useMutation({
    mutationFn: (body: { client_id: string; client_secret: string; tenant_domain: string }) =>
      unwrap(browserApi.POST("/api/v1/admin/sharepoint/app", { body })),
    onSuccess: () => {
      toast.success(t("sharepoint_app_configured_successfully"));
      void invalidate();
      setUpdatingSecret(false);
      onOpenChange(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const startOAuth = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/admin/sharepoint/service-account/auth/start", {
          body: {
            client_id: clientId.trim(),
            client_secret: clientSecret,
            tenant_domain: tenantDomain.trim()
          }
        })
      ),
    onSuccess: ({ auth_url, state }) => {
      sessionStorage.setItem(OAUTH_STATE_KEY, JSON.stringify({ state }));
      window.location.href = auth_url;
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("configure_sharepoint_app_title")}</DialogTitle>
          <DialogDescription>{t("sharepoint_app_config_description")}</DialogDescription>
        </DialogHeader>

        {isPending ? (
          <Skeleton className="h-40 w-full" />
        ) : config ? (
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-2 rounded-lg border p-3 text-sm">
              <span className="font-medium">{t("current_configuration")}</span>
              <Field label={t("service_account_option")} value={config.auth_method} />
              <Field label={t("client_id")} value={config.client_id} mono />
              <Field label={t("client_secret")} value={config.client_secret_masked} mono />
              <Field label={t("tenant_id_or_domain")} value={config.tenant_domain} />
              {config.service_account_email && (
                <Field label={t("service_account_option")} value={config.service_account_email} />
              )}
              <Badge variant={config.is_active ? "default" : "secondary"} className="w-fit">
                {config.is_active ? t("active") : t("inactive")}
              </Badge>
            </div>
            {updatingSecret ? (
              <div className="flex flex-col gap-2">
                <Label htmlFor="sp-new-secret">{t("new_client_secret")}</Label>
                <Input
                  id="sp-new-secret"
                  type="password"
                  autoComplete="off"
                  value={clientSecret}
                  onChange={(event) => setClientSecret(event.target.value)}
                />
              </div>
            ) : (
              <p className="text-muted-foreground text-xs">{t("sharepoint_change_auth_warning")}</p>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label>{t("service_account_option")}</Label>
              <Select value={authMethod} onValueChange={(v) => setAuthMethod(v as AuthMethod)}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="service_account">
                    {t("service_account_option")} · {t("recommended")}
                  </SelectItem>
                  <SelectItem value="tenant_app">{t("tenant_app_option")}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Labeled label={t("client_id")}>
              <Input value={clientId} onChange={(event) => setClientId(event.target.value)} />
            </Labeled>
            <Labeled label={t("client_secret")}>
              <Input
                type="password"
                autoComplete="off"
                value={clientSecret}
                onChange={(event) => setClientSecret(event.target.value)}
              />
            </Labeled>
            <Labeled label={t("tenant_id_or_domain")}>
              <Input
                placeholder={t("sharepoint_tenant_domain_placeholder")}
                value={tenantDomain}
                onChange={(event) => setTenantDomain(event.target.value)}
              />
            </Labeled>
            {testResult && (
              <p
                className={
                  testResult.ok
                    ? "rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700 dark:border-green-900 dark:bg-green-950 dark:text-green-400"
                    : "rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-400"
                }
              >
                {testResult.ok ? t("connection_successful") : t("connection_failed")}
                {testResult.message ? ` — ${testResult.message}` : ""}
              </p>
            )}
          </div>
        )}

        <DialogFooter className="flex-wrap gap-2">
          {config ? (
            updatingSecret ? (
              <>
                <Button variant="outline" onClick={() => setUpdatingSecret(false)}>
                  {t("back")}
                </Button>
                <Button
                  disabled={!clientSecret || save.isPending}
                  onClick={() =>
                    save.mutate({
                      client_id: config.client_id,
                      client_secret: clientSecret,
                      tenant_domain: config.tenant_domain
                    })
                  }
                >
                  {t("save")}
                </Button>
              </>
            ) : (
              <>
                <Button variant="outline" onClick={() => setUpdatingSecret(true)}>
                  {t("update_secret")}
                </Button>
                <Button variant="destructive" onClick={onRequestDelete}>
                  {t("delete_sharepoint_app")}
                </Button>
              </>
            )
          ) : authMethod === "tenant_app" ? (
            <>
              <Button
                variant="outline"
                disabled={test.isPending}
                onClick={() => requireFields() && test.mutate()}
              >
                {test.isPending ? t("testing_connection") : t("test_connection")}
              </Button>
              <Button
                disabled={save.isPending}
                onClick={() =>
                  requireFields() &&
                  save.mutate({
                    client_id: clientId.trim(),
                    client_secret: clientSecret,
                    tenant_domain: tenantDomain.trim()
                  })
                }
              >
                {t("save")}
              </Button>
            </>
          ) : (
            <Button
              disabled={startOAuth.isPending}
              onClick={() => requireFields() && startOAuth.mutate()}
            >
              {t("sign_in_with_microsoft")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Labeled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <Label>{label}</Label>
      {children}
    </div>
  );
}

function Field({ label, value, mono }: { label: string; value?: string | null; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-muted-foreground text-xs">{label}</span>
      <span className={mono ? "font-mono text-xs" : "text-xs"}>{value || "—"}</span>
    </div>
  );
}
