"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { FormLayout } from "@astryxdesign/core/FormLayout";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
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
  isProviderNameTaken,
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

/**
 * The provider's settings. Mounted while the dialog is open, so each opening
 * starts from the saved provider. Problems show at their fields on submit,
 * and focus moves to the first of them (WCAG 3.3.1).
 */
function ProviderEditForm({
  id,
  provider,
  takenName,
  onSubmit
}: {
  id: string;
  provider: ModelProvider;
  /** A name the save was refused for: another provider has it. */
  takenName: TakenName | null;
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
  const [apiKey, setApiKey] = useState("");
  const [apiKeyConfirmation, setApiKeyConfirmation] = useState("");
  const [configValues, setConfigValues] = useState(() => configToStrings(provider.config));
  const [keyExpiresOn, setKeyExpiresOn] = useState(provider.key_expires_on ?? null);
  const [submitted, setSubmitted] = useState(false);

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

  // The control pressed disappears, so focus moves to what replaced it.
  function startChangingKey() {
    flushSync(() => setChangingKey(true));
    focus.focus(NEW_KEY_FIELD.name);
  }

  function keepCurrentKey() {
    flushSync(() => {
      setChangingKey(false);
      setApiKey("");
      setApiKeyConfirmation("");
    });
    changeKeyRef.current?.focus();
  }

  function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const firstProblem = [
      name.trim() === "" ? "name" : null,
      changingKey ? providerFieldProblem(NEW_KEY_FIELD, apiKey, apiKeyConfirmation) : null,
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
      ...(changingKey ? { credentials: { api_key: apiKey.trim() } } : {}),
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
        {changingKey ? (
          <div className="flex flex-col gap-2">
            <ProviderField
              field={NEW_KEY_FIELD}
              providerType={provider.provider_type}
              value={apiKey}
              confirmation={apiKeyConfirmation}
              onValueChange={setApiKey}
              onConfirmationChange={setApiKeyConfirmation}
              showErrors={submitted}
              focus={focus}
            />
            <Button
              variant="ghost"
              size="sm"
              label={t("cancel_keep_current_key")}
              onClick={keepCurrentKey}
              className="self-start"
            />
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

  const save = useMutation({
    mutationFn: (body: ModelProviderUpdate) => updateProvider(browserApi, provider.id, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY });
      void queryClient.invalidateQueries({ queryKey: MODELS_KEY });
      toast.success(t("provider_updated_success"));
      setTakenName(null);
      onOpenChange(false);
    },
    // A taken name is shown at the name field; the toast's generic text
    // would speak of a model.
    onError: (error, body) => {
      if (isProviderNameTaken(error)) setTakenName({ name: body.name ?? "", at: Date.now() });
      else toastApiError(error, t);
    }
  });

  function requestOpenChange(next: boolean) {
    if (!next && save.isPending) return;
    if (!next) setTakenName(null);
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
