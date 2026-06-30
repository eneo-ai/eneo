"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { ProviderLogo } from "@/components/ai-elements/provider-logo";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { cn } from "@/lib/utils";
import { ModelCatalogStep } from "./model-catalog-step";
import {
  createProvider,
  FAVORITES_KEY,
  favoriteProvidersQueryOptions,
  modelProvidersQueryOptions,
  providerCapabilitiesQueryOptions,
  type ProviderCapabilities,
  providerDisplayName,
  providerFields,
  providerOptions,
  setFavoriteProviders
} from "./model-providers";
import { ProviderPicker } from "./provider-picker";

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

/** Provider-specific input hint shown inside a field (ported from the Svelte wizard). */
function fieldPlaceholder(t: (key: string) => string, name: string, providerType: string): string {
  switch (name) {
    case "api_key":
      return t("enter_api_key");
    case "endpoint":
      if (providerType === "azure") return "https://your-resource.openai.azure.com";
      if (providerType === "hosted_vllm") return "https://your-vllm-server.com";
      return "https://api.example.com/v1";
    case "api_version":
      return t("api_version_placeholder");
    case "deployment_name":
      return t("deployment_name_placeholder");
    default:
      return "";
  }
}

/** Provider-specific helper text shown below a field (ported from the Svelte wizard). */
function fieldHint(
  t: (key: string) => string,
  name: string,
  required: boolean,
  providerType: string
): string {
  switch (name) {
    case "api_key":
      return t("will_be_encrypted");
    case "endpoint":
      if (providerType === "azure") return t("endpoint_required_azure");
      if (providerType === "hosted_vllm") return t("endpoint_required_vllm");
      if (!required) return t("endpoint_optional_generic");
      return "";
    case "api_version":
      return t("api_version_required");
    case "deployment_name":
      return t("deployment_name_required");
    default:
      return "";
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

  const favoritesQuery = useQuery({
    ...favoriteProvidersQueryOptions(browserApi),
    enabled: open
  });
  const favorites = useMemo(() => new Set(favoritesQuery.data ?? []), [favoritesQuery.data]);
  const options = useMemo(() => (caps ? providerOptions(caps) : []), [caps]);

  const setFavoritesMut = useMutation({
    mutationFn: (next: string[]) => setFavoriteProviders(browserApi, next),
    onMutate: async (next) => {
      await queryClient.cancelQueries({ queryKey: FAVORITES_KEY });
      const previous = queryClient.getQueryData<string[]>(FAVORITES_KEY);
      queryClient.setQueryData(FAVORITES_KEY, next);
      return { previous };
    },
    onError: (error, _next, context) => {
      if (context?.previous) queryClient.setQueryData(FAVORITES_KEY, context.previous);
      toastApiError(error, t);
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: FAVORITES_KEY });
    }
  });

  function toggleFavorite(type: string) {
    const current = favoritesQuery.data ?? [];
    const next = current.includes(type)
      ? current.filter((value) => value !== type)
      : [...current, type];
    setFavoritesMut.mutate(next);
  }

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
    // Default to the provider gallery ("new"); the existing-provider path is a
    // secondary link. Adding models to a specific provider jumps past this step.
    setStep(initialProviderId ? "models" : "provider");
    setMode(initialProviderId ? "existing" : "new");
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
      <DialogContent
        className={cn(
          "max-h-[90vh] overflow-y-auto",
          // The provider gallery wants room for the card grid; the credentials
          // form stays narrow so it doesn't stretch into a sparse single column.
          step === "provider" ? "sm:max-w-4xl" : "sm:max-w-xl"
        )}
      >
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

        {step === "provider" &&
          (mode === "existing" ? (
            <div className="flex flex-col gap-4">
              {hasProviders && (
                <button
                  type="button"
                  onClick={() => setMode("new")}
                  className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 self-start text-sm"
                >
                  <ChevronLeft className="size-4" aria-hidden="true" />
                  {t("back_to_providers")}
                </button>
              )}
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
              <DialogFooter>
                <Button onClick={goNextFromProvider} disabled={!existingId}>
                  {t("next")}
                </Button>
              </DialogFooter>
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              {caps ? (
                <ProviderPicker
                  options={options}
                  favorites={favorites}
                  onSelect={(type) => {
                    setProviderType(type);
                    // Seed the editable name from the chosen provider, like Svelte.
                    setProviderName(providerDisplayName(type));
                    setStep("credentials");
                  }}
                  onToggleFavorite={toggleFavorite}
                />
              ) : (
                <div className="flex justify-center py-12">
                  <Spinner className="size-6" />
                </div>
              )}
              {hasProviders && (
                <button
                  type="button"
                  onClick={() => setMode("existing")}
                  className="text-muted-foreground hover:text-foreground self-center text-sm"
                >
                  {t("add_models_to_existing_provider")}
                </button>
              )}
            </div>
          ))}

        {step === "credentials" && (
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-3 rounded-lg border p-3">
              <ProviderLogo provider={providerType} className="size-7 shrink-0" />
              <div className="min-w-0">
                <div className="truncate font-medium">{providerDisplayName(providerType)}</div>
                <div className="text-muted-foreground text-sm">
                  {t("enter_provider_credentials")}
                </div>
              </div>
            </div>
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
                  placeholder={t("provider_name_placeholder")}
                  onChange={(event) => setProviderName(event.target.value)}
                />
                <p className="text-muted-foreground text-xs">{t("provider_name_hint")}</p>
              </div>
              {fields.map((field) => {
                const hint = fieldHint(t, field.name, field.required, providerType);
                return field.secret ? (
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
                    placeholder={fieldPlaceholder(t, field.name, providerType)}
                    description={hint || undefined}
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
                      placeholder={fieldPlaceholder(t, field.name, providerType)}
                      value={fieldValues[field.name] ?? ""}
                      onChange={(event) =>
                        setFieldValues((current) => ({
                          ...current,
                          [field.name]: event.target.value
                        }))
                      }
                    />
                    {hint && <p className="text-muted-foreground text-xs">{hint}</p>}
                  </div>
                );
              })}
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
          </div>
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
