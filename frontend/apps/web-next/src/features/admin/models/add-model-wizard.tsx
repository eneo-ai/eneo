"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import {
  ConfirmedPasswordField,
  isConfirmedPasswordValid
} from "@/components/composites/confirmed-password-field";
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
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { ModelCatalogStep } from "./model-catalog-step";
import {
  completionProviderTypes,
  createProvider,
  modelProvidersQueryOptions,
  providerCapabilitiesQueryOptions,
  type ProviderCapabilities,
  providerDisplayName,
  providerFields
} from "./model-providers";

type Step = "provider" | "credentials" | "models";

function fieldLabel(t: (key: string) => string, name: string): string {
  switch (name) {
    case "api_key":
      return t("api_key");
    case "endpoint":
      return t("endpoint_url");
    case "api_version":
      return t("api_version");
    case "deployment_name":
      return t("deployment_name");
    default:
      return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }
}

function confirmFieldLabel(t: (key: string) => string, name: string): string {
  switch (name) {
    case "api_key":
      return t("confirm_api_key");
    default:
      return t("confirm_secret");
  }
}

export function AddModelWizard({
  open,
  onOpenChange,
  initialProviderId
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialProviderId?: string;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const providers = useQuery({ ...modelProvidersQueryOptions(browserApi), enabled: open });
  const capsQuery = useQuery({ ...providerCapabilitiesQueryOptions(browserApi), enabled: open });
  const caps: ProviderCapabilities | undefined = capsQuery.data;

  const hasProviders = (providers.data?.length ?? 0) > 0;

  const [step, setStep] = useState<Step>("provider");
  const [mode, setMode] = useState<"existing" | "new">("new");
  const [existingId, setExistingId] = useState("");
  const [providerType, setProviderType] = useState("openai");
  const [providerName, setProviderName] = useState("");
  const [fieldValues, setFieldValues] = useState<Record<string, string>>({});
  const [fieldConfirmations, setFieldConfirmations] = useState<Record<string, string>>({});
  const [providerId, setProviderId] = useState<string | null>(null);

  function reset() {
    const preselect = initialProviderId ?? providers.data?.[0]?.id ?? "";
    const startExisting = Boolean(initialProviderId) || hasProviders;
    setStep(initialProviderId ? "models" : "provider");
    setMode(startExisting ? "existing" : "new");
    setExistingId(preselect);
    setProviderType("openai");
    setProviderName("");
    setFieldValues({});
    setFieldConfirmations({});
    setProviderId(initialProviderId ?? null);
  }

  function handleOpenChange(next: boolean) {
    if (next) reset();
    onOpenChange(next);
  }

  const fields = caps ? providerFields(caps, providerType) : [];

  const createProviderMut = useMutation({
    mutationFn: () => {
      const credentials: Record<string, string> = {};
      const config: Record<string, string> = {};
      for (const field of fields) {
        const value = fieldValues[field.name]?.trim();
        if (!value) continue;
        if (field.in === "config") config[field.name] = value;
        else credentials[field.name] = value;
      }
      return createProvider(browserApi, {
        name: providerName.trim() || providerDisplayName(providerType),
        provider_type: providerType,
        credentials,
        config
      });
    },
    onSuccess: (provider) => {
      void queryClient.invalidateQueries({ queryKey: ["admin-model-providers"] });
      setFieldValues({});
      setFieldConfirmations({});
      setProviderId(provider.id);
      setStep("models");
    },
    onError: (error) => toastApiError(error, t)
  });

  const requiredFieldsFilled = fields
    .filter((field) => field.required)
    .every((field) => (fieldValues[field.name] ?? "").trim() !== "");
  const secretFieldsConfirmed = fields
    .filter((field) => field.secret)
    .every((field) => {
      const value = fieldValues[field.name] ?? "";
      const confirmation = fieldConfirmations[field.name] ?? "";
      return isConfirmedPasswordValid({
        value,
        confirmation,
        required: field.required || value.length > 0 || confirmation.length > 0
      });
    });

  function goNextFromProvider() {
    if (mode === "existing") setStep("models");
    else setStep("credentials");
  }

  // Resolve the provider the model step adds to, plus its type (drives the catalog).
  const targetProviderId = mode === "existing" ? existingId : (providerId ?? "");
  const existingProvider = providers.data?.find((provider) => provider.id === existingId);
  const targetProviderType =
    mode === "existing" ? (existingProvider?.provider_type ?? "") : providerType;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("add_model")}</DialogTitle>
          <DialogDescription>
            {step === "provider"
              ? t("wizard_step_provider")
              : step === "credentials"
                ? t("wizard_step_credentials")
                : t("wizard_step_models")}
          </DialogDescription>
        </DialogHeader>

        {step === "provider" && (
          <div className="flex flex-col gap-4">
            <RadioGroup
              value={mode}
              onValueChange={(value) => setMode(value as "existing" | "new")}
              className="flex flex-col gap-2"
            >
              {hasProviders && (
                <Label className="flex items-center gap-2 font-normal">
                  <RadioGroupItem value="existing" /> {t("use_existing_provider")}
                </Label>
              )}
              <Label className="flex items-center gap-2 font-normal">
                <RadioGroupItem value="new" /> {t("new_provider")}
              </Label>
            </RadioGroup>

            {mode === "existing" ? (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="wizard-existing-provider">{t("provider")}</Label>
                <Select value={existingId} onValueChange={setExistingId}>
                  <SelectTrigger id="wizard-existing-provider" className="w-full">
                    <SelectValue placeholder={t("no_providers_configured")} />
                  </SelectTrigger>
                  <SelectContent>
                    {providers.data?.map((provider) => (
                      <SelectItem key={provider.id} value={provider.id}>
                        {provider.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ) : (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="wizard-provider-type">{t("provider_type")}</Label>
                <Select value={providerType} onValueChange={setProviderType}>
                  <SelectTrigger id="wizard-provider-type" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(caps ? completionProviderTypes(caps) : []).map((type) => (
                      <SelectItem key={type} value={type}>
                        {providerDisplayName(type)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            <DialogFooter>
              <Button
                onClick={goNextFromProvider}
                disabled={mode === "existing" ? !existingId : !caps}
              >
                {t("next")}
              </Button>
            </DialogFooter>
          </div>
        )}

        {step === "credentials" && (
          <form
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (requiredFieldsFilled && secretFieldsConfirmed) createProviderMut.mutate();
            }}
          >
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="wizard-provider-name">{t("provider_name")}</Label>
              <Input
                id="wizard-provider-name"
                value={providerName}
                placeholder={providerDisplayName(providerType)}
                onChange={(event) => setProviderName(event.target.value)}
              />
            </div>
            {fields.map((field) =>
              field.secret ? (
                <ConfirmedPasswordField
                  key={field.name}
                  id={`wizard-field-${field.name}`}
                  label={fieldLabel(t, field.name)}
                  confirmLabel={confirmFieldLabel(t, field.name)}
                  value={fieldValues[field.name] ?? ""}
                  confirmation={fieldConfirmations[field.name] ?? ""}
                  onValueChange={(value) =>
                    setFieldValues((current) => ({ ...current, [field.name]: value }))
                  }
                  onConfirmationChange={(value) =>
                    setFieldConfirmations((current) => ({ ...current, [field.name]: value }))
                  }
                  errorMessage={t("secret_values_do_not_match")}
                  autoComplete="off"
                  required={field.required}
                />
              ) : (
                <div key={field.name} className="flex flex-col gap-1.5">
                  <Label htmlFor={`wizard-field-${field.name}`}>
                    {fieldLabel(t, field.name)}
                    {field.required && <span aria-hidden="true"> *</span>}
                  </Label>
                  <Input
                    id={`wizard-field-${field.name}`}
                    type="text"
                    autoComplete="off"
                    required={field.required}
                    value={fieldValues[field.name] ?? ""}
                    onChange={(event) =>
                      setFieldValues((current) => ({
                        ...current,
                        [field.name]: event.target.value
                      }))
                    }
                  />
                </div>
              )
            )}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setStep("provider")}>
                {t("back")}
              </Button>
              <Button
                type="submit"
                disabled={
                  !requiredFieldsFilled || !secretFieldsConfirmed || createProviderMut.isPending
                }
              >
                {createProviderMut.isPending ? t("saving") : t("next")}
              </Button>
            </DialogFooter>
          </form>
        )}

        {step === "models" && targetProviderId && (
          <ModelCatalogStep
            providerId={targetProviderId}
            providerType={targetProviderType}
            onCreated={() => onOpenChange(false)}
            onBack={() => setStep(mode === "existing" ? "provider" : "credentials")}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
