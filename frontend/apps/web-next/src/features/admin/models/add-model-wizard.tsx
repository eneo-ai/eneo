"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
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
import { Switch } from "@/components/ui/switch";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import {
  completionProviderTypes,
  createCompletionModel,
  createProvider,
  modelProvidersQueryOptions,
  providerCapabilitiesQueryOptions,
  providerFields,
  type ProviderCapabilities
} from "./model-providers";
import { MODELS_KEY } from "./models";
import { providerDisplayName } from "./credentials";

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

export function AddModelWizard({
  open,
  onOpenChange
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
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
  const [providerId, setProviderId] = useState<string | null>(null);

  // Single model draft (re-run the wizard to add more).
  const [name, setName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [maxInput, setMaxInput] = useState("");
  const [maxOutput, setMaxOutput] = useState("");
  const [vision, setVision] = useState(false);
  const [reasoning, setReasoning] = useState(false);
  const [tools, setTools] = useState(false);

  function reset() {
    setStep("provider");
    setMode(hasProviders ? "existing" : "new");
    setExistingId(providers.data?.[0]?.id ?? "");
    setProviderType("openai");
    setProviderName("");
    setFieldValues({});
    setProviderId(null);
    setName("");
    setDisplayName("");
    setMaxInput("");
    setMaxOutput("");
    setVision(false);
    setReasoning(false);
    setTools(false);
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
      setProviderId(provider.id);
      setStep("models");
    },
    onError: (error) => toastApiError(error, t)
  });

  const createModelMut = useMutation({
    mutationFn: () => {
      const target = mode === "existing" ? existingId : providerId;
      if (!target) throw new Error("missing provider");
      return createCompletionModel(browserApi, {
        provider_id: target,
        name: name.trim(),
        display_name: displayName.trim() || name.trim(),
        max_input_tokens: maxInput ? Number(maxInput) : 0,
        max_output_tokens: maxOutput ? Number(maxOutput) : 0,
        vision,
        reasoning,
        supports_tool_calling: tools
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: MODELS_KEY });
      toast.success(t("model_created_success"));
      onOpenChange(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const requiredFieldsFilled = fields
    .filter((field) => field.required)
    .every((field) => (fieldValues[field.name] ?? "").trim() !== "");

  function goNextFromProvider() {
    if (mode === "existing") setStep("models");
    else setStep("credentials");
  }

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
              createProviderMut.mutate();
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
            {fields.map((field) => (
              <div key={field.name} className="flex flex-col gap-1.5">
                <Label htmlFor={`wizard-field-${field.name}`}>
                  {fieldLabel(t, field.name)}
                  {field.required && <span aria-hidden="true"> *</span>}
                </Label>
                <Input
                  id={`wizard-field-${field.name}`}
                  type={field.secret ? "password" : "text"}
                  autoComplete="off"
                  required={field.required}
                  value={fieldValues[field.name] ?? ""}
                  onChange={(event) =>
                    setFieldValues((current) => ({ ...current, [field.name]: event.target.value }))
                  }
                />
              </div>
            ))}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setStep("provider")}>
                {t("back")}
              </Button>
              <Button type="submit" disabled={!requiredFieldsFilled || createProviderMut.isPending}>
                {createProviderMut.isPending ? t("saving") : t("next")}
              </Button>
            </DialogFooter>
          </form>
        )}

        {step === "models" && (
          <form
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              createModelMut.mutate();
            }}
          >
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="wizard-model-name">{t("model_identifier")}</Label>
              <Input
                id="wizard-model-name"
                value={name}
                required
                onChange={(event) => setName(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="wizard-model-display">{t("display_name")}</Label>
              <Input
                id="wizard-model-display"
                value={displayName}
                placeholder={name}
                onChange={(event) => setDisplayName(event.target.value)}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="wizard-model-max-input">{t("max_input_tokens")}</Label>
                <Input
                  id="wizard-model-max-input"
                  type="number"
                  min={0}
                  inputMode="numeric"
                  value={maxInput}
                  onChange={(event) => setMaxInput(event.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="wizard-model-max-output">{t("max_output_tokens")}</Label>
                <Input
                  id="wizard-model-max-output"
                  type="number"
                  min={0}
                  inputMode="numeric"
                  value={maxOutput}
                  onChange={(event) => setMaxOutput(event.target.value)}
                />
              </div>
            </div>
            <fieldset className="flex flex-col gap-3">
              <legend className="text-muted-foreground mb-1 text-xs font-semibold tracking-wider uppercase">
                {t("capabilities")}
              </legend>
              <Label className="flex items-center justify-between gap-2 font-normal">
                {t("capability_vision")}
                <Switch checked={vision} onCheckedChange={setVision} />
              </Label>
              <Label className="flex items-center justify-between gap-2 font-normal">
                {t("reasoning")}
                <Switch checked={reasoning} onCheckedChange={setReasoning} />
              </Label>
              <Label className="flex items-center justify-between gap-2 font-normal">
                {t("model_label_tool_calling")}
                <Switch checked={tools} onCheckedChange={setTools} />
              </Label>
            </fieldset>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setStep(mode === "existing" ? "provider" : "credentials")}
              >
                {t("back")}
              </Button>
              <Button type="submit" disabled={!name.trim() || createModelMut.isPending}>
                {createModelMut.isPending ? t("saving") : t("create")}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
