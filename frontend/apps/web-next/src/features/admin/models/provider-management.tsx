"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { FormLayout } from "@astryxdesign/core/FormLayout";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@/components/astryx/text-input";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { Switch } from "@/components/astryx/switch";
import { useReturnFocus } from "@/components/ui/dialog-focus";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import { KeyExpiryField } from "./key-expiry-field";
import {
  comparableEndpoint,
  isProviderNameTaken,
  isProviderUpdateRefused,
  looksLikeMaskedApiKey,
  type ModelProvider,
  type ModelProviderUpdate,
  type ProviderFieldDef,
  PROVIDERS_KEY,
  providerCapabilitiesQueryOptions,
  providerDisplayName,
  providerFields,
  updateProvider
} from "./model-providers";
import { MODELS_KEY } from "./models";
import { ProviderField, providerFieldProblem, useFieldFocus } from "./provider-form-fields";

/** A new key replaces the stored one, so it is required once asked for. */
const NEW_KEY_FIELD: ProviderFieldDef = {
  name: "api_key",
  required: true,
  secret: true,
  in: "credentials"
};

function configToStrings(config: Record<string, unknown>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(config).map(([key, value]) => [key, value == null ? "" : String(value)])
  );
}

type TakenName = { name: string; at: number };
/** A key the backend refused (with the key as sent, "" when none was). */
type KeyRefusal = { key: string; message: string; at: number };

/**
 * The provider's settings. Mounted while the dialog is open, so each opening
 * starts from the saved provider. Problems show at their fields on submit,
 * and focus moves to the first of them (WCAG 3.3.1).
 *
 * A stored key is never sent to a destination it was not entered for, so
 * changing the endpoint of a provider that holds a key means typing the key
 * again; the field opens by itself and says why. The backend applies the
 * same rule and is authoritative: its refusal shows at the key field.
 */
function ProviderEditForm({
  id,
  provider,
  takenName,
  keyRefusal,
  onSubmit
}: {
  id: string;
  provider: ModelProvider;
  /** A name the save was refused for: another provider has it. */
  takenName: TakenName | null;
  /** A key (or its absence) the save was refused for. */
  keyRefusal: KeyRefusal | null;
  onSubmit: (body: ModelProviderUpdate) => void;
}) {
  const t = useTranslations();
  const capabilities = useQuery(providerCapabilitiesQueryOptions(browserApi));
  const focus = useFieldFocus();
  const keyLabelId = useId();
  const changeKeyRef = useRef<HTMLButtonElement>(null);
  const [name, setName] = useState(provider.name);
  const [isActive, setIsActive] = useState(provider.is_active);
  const [changingKey, setChangingKey] = useState(false);
  // A refusal the admin answered with "keep the current key" (by its time).
  const [dismissedRefusal, setDismissedRefusal] = useState<number | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [apiKeyConfirmation, setApiKeyConfirmation] = useState("");
  const [configValues, setConfigValues] = useState(() => configToStrings(provider.config));
  const [keyExpiresOn, setKeyExpiresOn] = useState(provider.key_expires_on ?? null);
  const [submitted, setSubmitted] = useState(false);
  // The endpoint the stored key was entered for, in comparable form.
  const [seededEndpoint] = useState(() =>
    comparableEndpoint(configToStrings(provider.config).endpoint ?? "")
  );
  const endpointChanged = comparableEndpoint(configValues.endpoint ?? "") !== seededEndpoint;
  const keyRequiredForEndpointChange = Boolean(provider.masked_api_key) && endpointChanged;
  // A refused key opens the field when it was not on screen (a save that sent none).
  const openedByRefusal = keyRefusal !== null && keyRefusal.at !== dismissedRefusal;
  const showKeyInput = changingKey || keyRequiredForEndpointChange || openedByRefusal;

  const configFields = capabilities.data
    ? providerFields(capabilities.data, provider.provider_type).filter(
        (field) => field.in === "config"
      )
    : [];

  const nameError =
    submitted && name.trim() === ""
      ? t("provider_form_name_required")
      : takenName && name.trim() === takenName.name
        ? t("provider_form_name_taken", { name: takenName.name })
        : null;
  // A refused save leaves focus on "Spara"; the problem is at the name.
  useEffect(() => {
    if (takenName) focus.focus("name");
  }, [takenName, focus]);
  // ... or at the key.
  useEffect(() => {
    if (keyRefusal) focus.focus(NEW_KEY_FIELD.name);
  }, [keyRefusal, focus]);
  const keyValueError =
    submitted && showKeyInput && looksLikeMaskedApiKey(apiKey)
      ? t("provider_form_api_key_masked")
      : keyRefusal && apiKey.trim() === keyRefusal.key
        ? keyRefusal.message
        : undefined;

  // The control pressed disappears, so focus moves to what replaced it.
  function startChangingKey() {
    flushSync(() => setChangingKey(true));
    focus.focus(NEW_KEY_FIELD.name);
  }

  function keepCurrentKey() {
    flushSync(() => {
      setChangingKey(false);
      setDismissedRefusal(keyRefusal?.at ?? null);
      setApiKey("");
      setApiKeyConfirmation("");
    });
    changeKeyRef.current?.focus();
  }

  function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const firstProblem = [
      name.trim() === "" ? "name" : null,
      showKeyInput ? providerFieldProblem(NEW_KEY_FIELD, apiKey, apiKeyConfirmation) : null,
      showKeyInput && looksLikeMaskedApiKey(apiKey) ? NEW_KEY_FIELD.name : null,
      ...configFields.map((field) =>
        providerFieldProblem(field, configValues[field.name] ?? "", "")
      )
    ].find((problem) => problem !== null);
    if (firstProblem) {
      // Rendered before focus moves, so the field is read with its error.
      flushSync(() => setSubmitted(true));
      focus.focus(firstProblem);
      return;
    }
    onSubmit({
      name: name.trim(),
      is_active: isActive,
      // Always sent: null removes a date the admin cleared.
      key_expires_on: keyExpiresOn,
      ...(showKeyInput ? { credentials: { api_key: apiKey.trim() } } : {}),
      ...(configFields.length > 0
        ? {
            config: Object.fromEntries(
              configFields.map((field) => [field.name, configValues[field.name]?.trim() ?? ""])
            )
          }
        : {})
    });
  }

  return (
    <form id={id} onSubmit={submit} noValidate>
      <FormLayout defaultOptionality="optional">
        <TextInput
          ref={focus.ref("name")}
          label={t("provider_name")}
          value={name}
          onChange={setName}
          isRequired
          autoComplete="off"
          placeholder={t("provider_name_placeholder")}
          status={nameError ? { type: "error", message: nameError } : undefined}
        />
        <Switch
          label={t("provider_is_active")}
          value={isActive}
          onChange={setIsActive}
          labelPosition="start"
          labelSpacing="spread"
        />
        {showKeyInput ? (
          <div className="flex flex-col gap-2">
            <ProviderField
              field={NEW_KEY_FIELD}
              providerType={provider.provider_type}
              value={apiKey}
              confirmation={apiKeyConfirmation}
              onValueChange={setApiKey}
              onConfirmationChange={setApiKeyConfirmation}
              description={
                keyRequiredForEndpointChange
                  ? t("provider_endpoint_change_requires_key")
                  : undefined
              }
              valueError={keyValueError}
              showErrors={submitted}
              focus={focus}
            />
            {/* The stored key cannot be kept for a new destination. */}
            {!keyRequiredForEndpointChange && (
              <Button
                variant="ghost"
                size="sm"
                label={t("cancel_keep_current_key")}
                onClick={keepCurrentKey}
                className="self-start"
              />
            )}
          </div>
        ) : (
          <div role="group" aria-labelledby={keyLabelId} className="flex flex-col gap-1">
            {/* Styled like the Astryx field labels around it. */}
            <Text type="label" color="secondary" id={keyLabelId}>
              {t("api_key")}
            </Text>
            <div className="flex flex-wrap items-center gap-3">
              <Text type="code">{provider.masked_api_key ?? t("provider_form_no_key")}</Text>
              <Button
                ref={changeKeyRef}
                size="sm"
                label={t("provider_form_change_key")}
                onClick={startChangingKey}
              >
                {t("change")}
              </Button>
            </div>
          </div>
        )}
        <KeyExpiryField value={keyExpiresOn} onChange={setKeyExpiresOn} />
        {configFields.length > 0 && (
          <fieldset className="flex min-w-0 flex-col gap-4">
            <legend className="text-ax-text mb-3 text-sm font-semibold">
              {t("configuration")}
            </legend>
            {configFields.map((field) => (
              <ProviderField
                key={field.name}
                field={field}
                providerType={provider.provider_type}
                value={configValues[field.name] ?? ""}
                onValueChange={(value) =>
                  setConfigValues((current) => ({ ...current, [field.name]: value }))
                }
                showErrors={submitted}
                focus={focus}
              />
            ))}
          </fieldset>
        )}
      </FormLayout>
    </form>
  );
}

/**
 * "Redigera leverantör", opened from the provider card's menu: name, on/off,
 * a new API key (typed twice), the key's expiry date and the type's config
 * fields. Focus returns to the menu's button when it closes.
 */
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
  const formId = useId();
  // The menu item that opened the dialog is gone once it is open.
  const noTrigger = useRef<HTMLElement>(null);
  useReturnFocus(open, noTrigger);
  const [takenName, setTakenName] = useState<TakenName | null>(null);
  const [keyRefusal, setKeyRefusal] = useState<KeyRefusal | null>(null);

  const save = useMutation({
    mutationFn: (body: ModelProviderUpdate) => updateProvider(browserApi, provider.id, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY });
      void queryClient.invalidateQueries({ queryKey: MODELS_KEY });
      toast.success(t("provider_updated_success"));
      setTakenName(null);
      setKeyRefusal(null);
      onOpenChange(false);
    },
    // A taken name is shown at the name field and a refused key at the key
    // field; the toast's generic text would speak of a model.
    onError: (error, body) => {
      if (isProviderNameTaken(error)) {
        setTakenName({ name: body.name ?? "", at: Date.now() });
      } else if (isProviderUpdateRefused(error)) {
        const sent = body.credentials?.api_key;
        setKeyRefusal({
          key: typeof sent === "string" ? sent : "",
          message: error.message,
          at: Date.now()
        });
      } else {
        toastApiError(error, t);
      }
    }
  });

  function requestOpenChange(next: boolean) {
    if (!next && save.isPending) return;
    if (!next) {
      setTakenName(null);
      setKeyRefusal(null);
    }
    onOpenChange(next);
  }

  // The header stays mounted: Astryx names the dialog from the title present
  // when it mounts. The form and its buttons exist only while it is open.
  return (
    <Dialog
      isOpen={open}
      onOpenChange={requestOpenChange}
      purpose="form"
      width={520}
      maxHeight="calc(100dvh - 2rem)"
    >
      <Layout
        header={
          <DialogHeader
            title={t("edit_provider")}
            subtitle={providerDisplayName(provider.provider_type)}
            onOpenChange={requestOpenChange}
          />
        }
        content={
          open ? (
            <LayoutContent>
              <ProviderEditForm
                id={formId}
                provider={provider}
                takenName={takenName}
                keyRefusal={keyRefusal}
                onSubmit={(body) => {
                  if (!save.isPending) save.mutate(body);
                }}
              />
            </LayoutContent>
          ) : null
        }
        footer={
          open ? (
            <LayoutFooter>
              <div className="flex flex-wrap justify-end gap-2">
                <Button
                  label={t("cancel")}
                  isDisabled={save.isPending}
                  onClick={() => requestOpenChange(false)}
                />
                <Button
                  type="submit"
                  form={formId}
                  variant="primary"
                  label={t("save")}
                  // Keeps focus while saving; the form ignores a second press.
                  isLoading={save.isPending}
                  isInterruptible
                />
              </div>
            </LayoutFooter>
          ) : null
        }
      />
    </Dialog>
  );
}
