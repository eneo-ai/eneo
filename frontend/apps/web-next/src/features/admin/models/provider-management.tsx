"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import {
  ConfirmedPasswordField,
  isConfirmedPasswordValid
} from "@/components/composites/confirmed-password-field";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import {
  type ModelProvider,
  PROVIDERS_KEY,
  providerCapabilitiesQueryOptions,
  providerFieldHint,
  providerFieldLabel,
  providerFieldPlaceholder,
  providerFields,
  updateProvider
} from "./model-providers";
import { MODELS_KEY } from "./models";

function configToStrings(config: Record<string, unknown>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(config).map(([key, value]) => [key, value == null ? "" : String(value)])
  );
}

export function ProviderEditDialog({
  provider,
  open,
  onOpenChange
}: {
  provider: ModelProvider;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const capabilities = useQuery({
    ...providerCapabilitiesQueryOptions(browserApi),
    enabled: open
  });
  const [name, setName] = useState(provider.name);
  const [isActive, setIsActive] = useState(provider.is_active);
  const [changingKey, setChangingKey] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [apiKeyConfirmation, setApiKeyConfirmation] = useState("");
  const [configValues, setConfigValues] = useState(() => configToStrings(provider.config));
  const apiKeyValid = isConfirmedPasswordValid({
    value: apiKey,
    confirmation: apiKeyConfirmation,
    required: changingKey
  });
  const apiKeyReady = apiKey.trim().length > 0 && apiKeyValid;
  const configFields = capabilities.data
    ? providerFields(capabilities.data, provider.provider_type).filter(
        (field) => field.in === "config"
      )
    : [];
  const configReady = configFields.every(
    (field) => !field.required || (configValues[field.name] ?? "").trim() !== ""
  );

  function clearApiKey() {
    setApiKey("");
    setApiKeyConfirmation("");
  }

  const save = useMutation({
    mutationFn: () =>
      updateProvider(browserApi, provider.id, {
        name: name.trim(),
        is_active: isActive,
        ...(changingKey && apiKeyReady ? { credentials: { api_key: apiKey } } : {}),
        ...(configFields.length > 0
          ? {
              config: Object.fromEntries(
                configFields.map((field) => [field.name, configValues[field.name]?.trim() ?? ""])
              )
            }
          : {})
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY });
      void queryClient.invalidateQueries({ queryKey: MODELS_KEY });
      toast.success(t("provider_updated_success"));
      clearApiKey();
      onOpenChange(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) clearApiKey();
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {t("edit_provider")} — {provider.provider_type}
          </DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="provider-edit-name">{t("provider_name")}</Label>
            <Input
              id="provider-edit-name"
              value={name}
              placeholder={t("provider_name_placeholder")}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <Label className="flex items-center justify-between gap-2 font-normal">
            {t("provider_is_active")}
            <Switch checked={isActive} onCheckedChange={setIsActive} />
          </Label>
          {changingKey ? (
            <div className="flex flex-col gap-1.5">
              <ConfirmedPasswordField
                id="provider-edit-api-key"
                label={t("api_key")}
                confirmLabel={t("confirm_api_key")}
                value={apiKey}
                confirmation={apiKeyConfirmation}
                onValueChange={setApiKey}
                onConfirmationChange={setApiKeyConfirmation}
                errorMessage={t("secret_values_do_not_match")}
                autoComplete="off"
                required
              />
              <Button
                type="button"
                variant="link"
                size="sm"
                className="w-fit px-0"
                onClick={() => {
                  setChangingKey(false);
                  clearApiKey();
                }}
              >
                {t("cancel_keep_current_key")}
              </Button>
            </div>
          ) : (
            <div className="flex flex-col gap-1.5">
              <Label>{t("api_key")}</Label>
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground font-mono text-xs">
                  {provider.masked_api_key ?? "••••"}
                </span>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setChangingKey(true)}
                >
                  {t("change")}
                </Button>
              </div>
            </div>
          )}
          {configFields.length > 0 && (
            <fieldset className="flex flex-col gap-3">
              <legend className="text-muted-foreground text-xs font-semibold tracking-wider uppercase">
                {t("configuration")}
              </legend>
              {configFields.map((field) => {
                const hint = providerFieldHint(
                  t,
                  field.name,
                  field.required,
                  provider.provider_type
                );
                return (
                  <div key={field.name} className="flex flex-col gap-1.5">
                    <Label htmlFor={`provider-config-${field.name}`}>
                      {providerFieldLabel(t, field.name)}
                      {field.required && <span aria-hidden="true"> *</span>}
                    </Label>
                    <Input
                      id={`provider-config-${field.name}`}
                      value={configValues[field.name] ?? ""}
                      required={field.required}
                      placeholder={providerFieldPlaceholder(t, field.name, provider.provider_type)}
                      onChange={(event) =>
                        setConfigValues((current) => ({
                          ...current,
                          [field.name]: event.target.value
                        }))
                      }
                    />
                    {hint && <p className="text-muted-foreground text-xs">{hint}</p>}
                  </div>
                );
              })}
            </fieldset>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            disabled={
              save.isPending || !name.trim() || !configReady || (changingKey && !apiKeyReady)
            }
            onClick={() => save.mutate()}
          >
            {save.isPending ? t("saving") : t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
