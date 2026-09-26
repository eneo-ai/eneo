"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { FormLayout } from "@astryxdesign/core/FormLayout";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@/components/astryx/text-input";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { ProviderLogo } from "@/components/ai-elements/provider-logo";
import { LoadingState } from "@/components/composites/loading-state";
import { useReturnFocus } from "@/components/ui/dialog-focus";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { KeyExpiryField } from "./key-expiry-field";
import { ModelCatalogStep } from "./model-catalog-step";
import {
  createProvider,
  FAVORITES_KEY,
  favoriteProvidersQueryOptions,
  isProviderNameTaken,
  modelProvidersQueryOptions,
  PROVIDERS_KEY,
  providerCapabilitiesQueryOptions,
  type ProviderCapabilities,
  providerDisplayName,
  providerFields,
  providerOptions,
  setFavoriteProviders
} from "./model-providers";
import type { ModelKind } from "./models";
import { ProviderField, providerFieldProblem, useFieldFocus } from "./provider-form-fields";
import { ProviderPicker } from "./provider-picker";

/**
 * Where a step change moves focus: the new step's first field (a text field
 * or a picker), else its first control.
 */
const STEP_FOCUS = [
  'input:not([disabled]):not([type="hidden"]), [role="combobox"]:not([aria-disabled="true"]), textarea:not([disabled])',
  'button:not([disabled]), a[href], [tabindex="0"]'
];

type Step = "provider" | "credentials" | "models";

function supportedModelKinds(modes: string[] | undefined): ModelKind[] {
  const ordered: ModelKind[] = ["completion", "embedding", "transcription"];
  const modeSet = new Set(modes ?? []);
  const supported = ordered.filter((mode) => modeSet.has(mode));
  return supported.length > 0 ? supported : ["completion"];
}
function defaultModelKind(modes: string[] | undefined): ModelKind {
  return supportedModelKinds(modes)[0] ?? "completion";
}

/**
 * "Lägg till modell" / "Lägg till leverantör": pick a provider type (or an
 * existing provider), enter its credentials, then pick models from its
 * catalog. Each step is a form whose problems show at their fields when it
 * is submitted; focus moves to the first of them, and on each step change to
 * the new step's first control.
 */
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
  const [keyExpiresOn, setKeyExpiresOn] = useState<string | null>(null);
  const [providerId, setProviderId] = useState<string | null>(null);
  const [modelKind, setModelKind] = useState<ModelKind>("completion");
  const [credentialsSubmitted, setCredentialsSubmitted] = useState(false);
  /** A name the create was refused for: another provider has it. */
  const [takenName, setTakenName] = useState<string | null>(null);
  const focus = useFieldFocus();
  const credentialsFormId = useId();
  // Also where Safari never focused the button that opened the wizard.
  const noTrigger = useRef<HTMLElement>(null);
  useReturnFocus(open, noTrigger);

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
    setKeyExpiresOn(null);
    setCredentialsSubmitted(false);
    setTakenName(null);
    setProviderId(initialProviderId ?? null);
    const provider = providers.data?.find((item) => item.id === preselect);
    setModelKind(defaultModelKind(caps?.providers[provider?.provider_type ?? ""]?.modes));
  }

  // The dialog is opened from outside (no Radix trigger), so Radix never
  // reports the opening: start a fresh session whenever `open` turns true,
  // adjusting state during render instead of in an effect.
  const [sessionOpen, setSessionOpen] = useState(false);
  if (open !== sessionOpen) {
    setSessionOpen(open);
    if (open) reset();
  }

  const fields = caps ? providerFields(caps, providerType) : [];
  // An empty name falls back to the type's own.
  const newProviderName = providerName.trim() || providerDisplayName(providerType);

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
        name: newProviderName,
        provider_type: providerType,
        credentials,
        config,
        key_expires_on: keyExpiresOn
      });
    },
    onSuccess: (provider) => {
      void queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY });
      setFieldValues({});
      setFieldConfirmations({});
      setCredentialsSubmitted(false);
      setProviderId(provider.id);
      setExistingId(provider.id);
      setMode("existing");
      setModelKind(defaultModelKind(caps?.providers[provider.provider_type]?.modes));
      setStep("models");
    },
    // A taken name is shown at the name field; the toast's generic text
    // would speak of a model.
    onError: (error) => {
      if (!isProviderNameTaken(error)) {
        toastApiError(error, t);
        return;
      }
      flushSync(() => setTakenName(newProviderName));
      focus.focus("name");
    }
  });

  function submitCredentials(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (createProviderMut.isPending) return;
    const firstProblem = fields
      .map((field) =>
        providerFieldProblem(
          field,
          fieldValues[field.name] ?? "",
          fieldConfirmations[field.name] ?? ""
        )
      )
      .find((problem) => problem !== null);
    if (firstProblem) {
      // Rendered before focus moves, so the field is read with its error.
      flushSync(() => setCredentialsSubmitted(true));
      focus.focus(firstProblem);
      return;
    }
    createProviderMut.mutate();
  }

  function requestOpenChange(next: boolean) {
    if (!next && createProviderMut.isPending) return;
    onOpenChange(next);
  }

  // Resolve the provider the model step adds to, plus its type (drives the catalog).
  const targetProviderId = mode === "existing" ? existingId : (providerId ?? "");
  const createdProvider = providerId
    ? providers.data?.find((provider) => provider.id === providerId)
    : undefined;
  const existingProvider =
    providers.data?.find((provider) => provider.id === existingId) ?? createdProvider;
  const targetProviderType =
    mode === "existing" ? (existingProvider?.provider_type ?? "") : providerType;
  const targetProviderModes = supportedModelKinds(caps?.providers[targetProviderType]?.modes);
  const effectiveModelKind = targetProviderModes.includes(modelKind)
    ? modelKind
    : (targetProviderModes[0] ?? "completion");

  // A step change removes the control that had focus (the tile, "Nästa"):
  // focus moves into the new step instead of the page.
  const contentRef = useRef<HTMLDivElement>(null);
  const view = `${step}:${mode}`;
  const shownView = useRef<string | null>(null);
  useEffect(() => {
    if (!open) {
      shownView.current = null;
      return;
    }
    if (shownView.current !== null && shownView.current !== view) {
      const content = contentRef.current;
      STEP_FOCUS.map((selector) => content?.querySelector<HTMLElement>(selector))
        .find(Boolean)
        ?.focus();
    }
    shownView.current = view;
  }, [open, view]);

  const stepLabel =
    step === "provider"
      ? t("wizard_step_provider")
      : step === "credentials"
        ? t("wizard_step_credentials")
        : t("wizard_step_models");

  // The header stays mounted: Astryx names the dialog from the title present
  // when it mounts. Steps fill the content and footer while it is open.
  function frame(content?: React.ReactNode, footer?: React.ReactNode) {
    return (
      <Layout
        header={
          <DialogHeader
            title={t("add_model")}
            subtitle={open ? stepLabel : undefined}
            onOpenChange={requestOpenChange}
          />
        }
        content={
          content ? (
            <LayoutContent>
              <div ref={contentRef}>{content}</div>
            </LayoutContent>
          ) : null
        }
        footer={
          footer ? (
            <LayoutFooter>
              <div className="flex flex-wrap justify-end gap-2">{footer}</div>
            </LayoutFooter>
          ) : null
        }
      />
    );
  }

  function providerStep() {
    if (mode === "existing") {
      return frame(
        <div className="flex flex-col gap-4">
          {hasProviders && (
            <Button
              variant="ghost"
              size="sm"
              label={t("back_to_providers")}
              icon={<ChevronLeft className="size-4" aria-hidden="true" />}
              onClick={() => setMode("new")}
              className="self-start"
            />
          )}
          <Selector
            label={t("provider")}
            options={(providers.data ?? []).map((provider) => ({
              value: provider.id,
              label: provider.name
            }))}
            value={existingId || undefined}
            placeholder={t("no_providers_configured")}
            onChange={(id) => {
              setExistingId(id);
              const provider = providers.data?.find((item) => item.id === id);
              setModelKind(defaultModelKind(caps?.providers[provider?.provider_type ?? ""]?.modes));
            }}
          />
        </div>,
        <Button
          variant="primary"
          label={t("next")}
          isDisabled={!existingId}
          onClick={() => setStep("models")}
        />
      );
    }
    return frame(
      <div className="flex flex-col gap-4">
        {/* Before the gallery: after it, a keyboard user would tab past every tile. */}
        {hasProviders && (
          <Button
            variant="ghost"
            label={t("add_models_to_existing_provider")}
            onClick={() => setMode("existing")}
            className="self-start"
          />
        )}
        {caps ? (
          <ProviderPicker
            options={options}
            favorites={favorites}
            onSelect={(type) => {
              setProviderType(type);
              // Seed the editable name from the chosen provider, like Svelte.
              setProviderName(providerDisplayName(type));
              setModelKind(defaultModelKind(caps?.providers[type]?.modes));
              setCredentialsSubmitted(false);
              setStep("credentials");
            }}
            onToggleFavorite={toggleFavorite}
          />
        ) : (
          <LoadingState rows={4} />
        )}
      </div>
    );
  }

  function credentialsStep() {
    return frame(
      <div className="flex flex-col gap-5">
        <div className="border-ax-border rounded-ax-container flex items-center gap-3 border p-3">
          <ProviderLogo provider={providerType} className="size-7 shrink-0" />
          <div className="min-w-0">
            <Text type="label" display="block">
              {providerDisplayName(providerType)}
            </Text>
            <Text type="supporting">{t("enter_provider_credentials")}</Text>
          </div>
        </div>
        <form id={credentialsFormId} onSubmit={submitCredentials} noValidate>
          <FormLayout defaultOptionality="optional">
            <TextInput
              ref={focus.ref("name")}
              label={t("provider_name")}
              description={t("provider_name_hint")}
              value={providerName}
              onChange={setProviderName}
              autoComplete="off"
              placeholder={t("provider_name_placeholder")}
              status={
                takenName === newProviderName
                  ? { type: "error", message: t("provider_form_name_taken", { name: takenName }) }
                  : undefined
              }
            />
            {fields.map((field) => (
              <ProviderField
                key={field.name}
                field={field}
                providerType={providerType}
                value={fieldValues[field.name] ?? ""}
                confirmation={fieldConfirmations[field.name] ?? ""}
                onValueChange={(value) =>
                  setFieldValues((current) => ({ ...current, [field.name]: value }))
                }
                onConfirmationChange={(value) =>
                  setFieldConfirmations((current) => ({ ...current, [field.name]: value }))
                }
                showErrors={credentialsSubmitted}
                focus={focus}
              />
            ))}
            <KeyExpiryField value={keyExpiresOn} onChange={setKeyExpiresOn} />
          </FormLayout>
        </form>
      </div>,
      <>
        <Button
          label={t("back")}
          isDisabled={createProviderMut.isPending}
          onClick={() => setStep("provider")}
        />
        <Button
          type="submit"
          form={credentialsFormId}
          variant="primary"
          label={t("next")}
          // Keeps focus while the provider is created; a second press is ignored.
          isLoading={createProviderMut.isPending}
          isInterruptible
        />
      </>
    );
  }

  return (
    <Dialog
      isOpen={open}
      onOpenChange={requestOpenChange}
      purpose="form"
      // The provider gallery wants room for the card grid; the forms stay
      // narrow so they don't stretch into a sparse single column.
      width={step === "provider" && mode === "new" ? 896 : 576}
      maxHeight="calc(100dvh - 2rem)"
    >
      {!open
        ? frame()
        : step === "provider"
          ? providerStep()
          : step === "credentials"
            ? credentialsStep()
            : targetProviderId && (
                <ModelCatalogStep
                  providerId={targetProviderId}
                  providerType={targetProviderType}
                  mode={effectiveModelKind}
                  supportedModes={targetProviderModes}
                  onModeChange={setModelKind}
                  onCreated={() => onOpenChange(false)}
                  onBack={() => setStep("provider")}
                  frame={frame}
                />
              )}
    </Dialog>
  );
}
