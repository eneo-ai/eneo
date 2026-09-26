"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { flushSync } from "react-dom";
import {
  ConfirmedSecretInput,
  confirmedSecretProblem
} from "@/components/composites/confirmed-secret-input";
import { FieldProblem, fieldProblemProps } from "@/components/composites/field-problem";
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
import { toast } from "@/lib/toast";
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
  const [clientSecretConfirmation, setClientSecretConfirmation] = useState("");
  const [tenantDomain, setTenantDomain] = useState("");
  const [updatingSecret, setUpdatingSecret] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message?: string } | null>(null);
  const clientIdRef = useRef<HTMLInputElement>(null);
  const secretRef = useRef<HTMLInputElement>(null);
  const secretConfirmationRef = useRef<HTMLInputElement>(null);
  const tenantDomainRef = useRef<HTMLInputElement>(null);
  const updateSecretRef = useRef<HTMLButtonElement>(null);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: SHAREPOINT_APP_KEY });
  const clientIdProblem = clientId.trim() ? null : t("required_field");
  const tenantDomainProblem = tenantDomain.trim() ? null : t("required_field");
  const secretProblem = confirmedSecretProblem({
    value: clientSecret,
    confirmation: clientSecretConfirmation,
    isRequired: true
  });
  // Only spaces is no secret either.
  const secretBlank = clientSecret !== "" && clientSecret.trim() === "";
  const shown = (problem: string | null) => (submitted ? problem : null);
  function clearClientSecret() {
    setClientSecret("");
    setClientSecretConfirmation("");
    setSubmitted(false);
  }

  // The button pressed disappears, so focus moves to what replaced it: the
  // new secret's field, and back to "Uppdatera secret" once the fields go.
  function startUpdatingSecret() {
    flushSync(() => {
      clearClientSecret();
      setUpdatingSecret(true);
    });
    secretRef.current?.focus();
  }

  function stopUpdatingSecret() {
    flushSync(() => {
      setUpdatingSecret(false);
      clearClientSecret();
    });
    updateSecretRef.current?.focus();
  }

  /**
   * Shows the problems at their fields and moves focus to the first (the
   * fields in order: the client ID, the secret and its confirmation, the
   * tenant); false while there is one. Only the secret when it is replaced.
   */
  function checkFields(): boolean {
    const firstProblem =
      !config && clientIdProblem
        ? clientIdRef
        : secretProblem === "required" || secretBlank
          ? secretRef
          : secretProblem === "mismatch"
            ? secretConfirmationRef
            : !config && tenantDomainProblem
              ? tenantDomainRef
              : null;
    if (!firstProblem) return true;
    // Rendered before focus moves, so the field is read with its error.
    flushSync(() => setSubmitted(true));
    firstProblem.current?.focus();
    return false;
  }

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
      clearClientSecret();
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
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          clearClientSecret();
          setUpdatingSecret(false);
        }
        onOpenChange(next);
      }}
    >
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
              <ConfirmedSecretInput
                label={t("new_client_secret")}
                confirmLabel={t("confirm_client_secret")}
                value={clientSecret}
                confirmation={clientSecretConfirmation}
                onValueChange={setClientSecret}
                onConfirmationChange={setClientSecretConfirmation}
                mismatchMessage={t("secret_values_do_not_match")}
                autoComplete="off"
                isRequired
                requiredMessage={t("required_field")}
                valueError={submitted && secretBlank ? t("required_field") : undefined}
                showErrors={submitted}
                valueRef={secretRef}
                confirmationRef={secretConfirmationRef}
              />
            ) : (
              <p className="text-muted-foreground text-xs">{t("sharepoint_change_auth_warning")}</p>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="sp-auth-method">{t("service_account_option")}</Label>
              <Select value={authMethod} onValueChange={(v) => setAuthMethod(v as AuthMethod)}>
                <SelectTrigger id="sp-auth-method" className="w-full">
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
            <Labeled label={t("client_id")} htmlFor="sp-client-id">
              <Input
                ref={clientIdRef}
                id="sp-client-id"
                value={clientId}
                onChange={(event) => setClientId(event.target.value)}
                {...fieldProblemProps("sp-client-id", shown(clientIdProblem))}
              />
              <FieldProblem id="sp-client-id" problem={shown(clientIdProblem)} />
            </Labeled>
            <ConfirmedSecretInput
              label={t("client_secret")}
              confirmLabel={t("confirm_client_secret")}
              value={clientSecret}
              confirmation={clientSecretConfirmation}
              onValueChange={setClientSecret}
              onConfirmationChange={setClientSecretConfirmation}
              mismatchMessage={t("secret_values_do_not_match")}
              autoComplete="off"
              isRequired
              requiredMessage={t("required_field")}
              valueError={submitted && secretBlank ? t("required_field") : undefined}
              showErrors={submitted}
              valueRef={secretRef}
              confirmationRef={secretConfirmationRef}
            />
            <Labeled label={t("tenant_id_or_domain")} htmlFor="sp-tenant-domain">
              <Input
                ref={tenantDomainRef}
                id="sp-tenant-domain"
                placeholder={t("sharepoint_tenant_domain_placeholder")}
                value={tenantDomain}
                onChange={(event) => setTenantDomain(event.target.value)}
                {...fieldProblemProps("sp-tenant-domain", shown(tenantDomainProblem))}
              />
              <FieldProblem id="sp-tenant-domain" problem={shown(tenantDomainProblem)} />
            </Labeled>
            {testResult && (
              <p
                className={
                  testResult.ok
                    ? "border-success/30 bg-success/10 text-success rounded-md border px-3 py-2 text-sm"
                    : "border-destructive/30 bg-destructive/10 text-destructive rounded-md border px-3 py-2 text-sm"
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
                <Button variant="outline" onClick={stopUpdatingSecret}>
                  {t("back")}
                </Button>
                <Button
                  aria-busy={save.isPending || undefined}
                  onClick={() => {
                    if (save.isPending || !checkFields()) return;
                    save.mutate({
                      client_id: config.client_id,
                      client_secret: clientSecret,
                      tenant_domain: config.tenant_domain
                    });
                  }}
                >
                  {t("save")}
                </Button>
              </>
            ) : (
              <>
                <Button ref={updateSecretRef} variant="outline" onClick={startUpdatingSecret}>
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
                aria-busy={test.isPending || undefined}
                onClick={() => {
                  if (!test.isPending && checkFields()) test.mutate();
                }}
              >
                {test.isPending ? t("testing_connection") : t("test_connection")}
              </Button>
              <Button
                aria-busy={save.isPending || undefined}
                onClick={() => {
                  if (save.isPending || !checkFields()) return;
                  save.mutate({
                    client_id: clientId.trim(),
                    client_secret: clientSecret,
                    tenant_domain: tenantDomain.trim()
                  });
                }}
              >
                {t("save")}
              </Button>
            </>
          ) : (
            <Button
              aria-busy={startOAuth.isPending || undefined}
              onClick={() => {
                if (!startOAuth.isPending && checkFields()) startOAuth.mutate();
              }}
            >
              {t("sign_in_with_microsoft")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Labeled({
  label,
  htmlFor,
  children
}: {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={htmlFor}>{label}</Label>
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
