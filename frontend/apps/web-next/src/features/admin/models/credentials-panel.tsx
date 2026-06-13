"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { ProviderLogo } from "@/components/ai-elements/provider-logo";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
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
import { Skeleton } from "@/components/ui/skeleton";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import {
  AZURE_PROVIDER,
  CREDENTIAL_PROVIDERS,
  CREDENTIALS_KEY,
  type CredentialInfo,
  type CredentialProvider,
  credentialsQueryOptions,
  providerDisplayName,
  setCredential
} from "./credentials";
import { MODELS_KEY } from "./models";

function SetCredentialDialog({
  provider,
  configured,
  open,
  onOpenChange
}: {
  provider: CredentialProvider;
  configured: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const isAzure = provider === AZURE_PROVIDER;

  const [apiKey, setApiKey] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [apiVersion, setApiVersion] = useState("");
  const [deploymentName, setDeploymentName] = useState("");

  const save = useMutation({
    mutationFn: () =>
      setCredential(browserApi, provider, {
        api_key: apiKey,
        endpoint: isAzure ? endpoint || undefined : undefined,
        api_version: isAzure ? apiVersion || undefined : undefined,
        deployment_name: isAzure ? deploymentName || undefined : undefined
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: CREDENTIALS_KEY });
      // Setting a key unlocks the provider's models, so refresh the model list.
      void queryClient.invalidateQueries({ queryKey: MODELS_KEY });
      toast.success(t("credential_saved"));
      onOpenChange(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {configured ? t("update_api_key") : t("set_api_key")} — {providerDisplayName(provider)}
          </DialogTitle>
          <DialogDescription>{t("api_credentials_hint")}</DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate();
          }}
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="credential-api-key">{t("api_key")}</Label>
            <Input
              id="credential-api-key"
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              required
            />
          </div>
          {isAzure && (
            <>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="credential-endpoint">{t("endpoint")}</Label>
                <Input
                  id="credential-endpoint"
                  value={endpoint}
                  onChange={(event) => setEndpoint(event.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="credential-api-version">{t("api_version")}</Label>
                <Input
                  id="credential-api-version"
                  value={apiVersion}
                  onChange={(event) => setApiVersion(event.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="credential-deployment">{t("deployment_name")}</Label>
                <Input
                  id="credential-deployment"
                  value={deploymentName}
                  onChange={(event) => setDeploymentName(event.target.value)}
                />
              </div>
            </>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={save.isPending || !apiKey.trim()}>
              {save.isPending ? t("saving") : t("save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ProviderCredentialCard({
  provider,
  info
}: {
  provider: CredentialProvider;
  info?: CredentialInfo;
}) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const configured = Boolean(info);

  return (
    <Card className="flex items-center justify-between gap-4 p-4">
      <div className="flex min-w-0 items-center gap-3">
        <ProviderLogo provider={provider} className="size-6" />
        <div className="flex min-w-0 flex-col">
          <span className="font-medium">{providerDisplayName(provider)}</span>
          {configured ? (
            <span className="text-muted-foreground font-mono text-xs">{info?.masked_key}</span>
          ) : (
            <span className="text-muted-foreground text-xs">{t("not_configured")}</span>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2">
        {configured && <Badge variant="secondary">{t("configured")}</Badge>}
        <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
          {configured ? t("update_api_key") : t("set_api_key")}
        </Button>
      </div>
      <SetCredentialDialog
        provider={provider}
        configured={configured}
        open={open}
        onOpenChange={setOpen}
      />
    </Card>
  );
}

/** Per-provider API credential management (set/update encrypted keys). */
export function CredentialsPanel() {
  const t = useTranslations();
  const { data, isPending } = useQuery(credentialsQueryOptions(browserApi));

  if (isPending) return <Skeleton className="h-64 w-full" />;

  const byProvider = new Map((data ?? []).map((info) => [info.provider, info]));

  return (
    <div className="flex flex-col gap-4">
      <p className="text-muted-foreground text-sm">{t("api_credentials_hint")}</p>
      <div className="flex flex-col gap-3">
        {CREDENTIAL_PROVIDERS.map((provider) => (
          <ProviderCredentialCard
            key={provider}
            provider={provider}
            info={byProvider.get(provider)}
          />
        ))}
      </div>
    </div>
  );
}
