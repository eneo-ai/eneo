"use client";

import { TextInput } from "@/components/astryx/text-input";
import { useTranslations } from "next-intl";
import { useMemo, useRef } from "react";
import {
  ConfirmedSecretInput,
  confirmedSecretProblem
} from "@/components/composites/confirmed-secret-input";
import {
  providerConfirmFieldLabel,
  type ProviderFieldDef,
  providerFieldHint,
  providerFieldLabel,
  providerFieldPlaceholder
} from "./model-providers";

type Translate = ReturnType<typeof useTranslations>;

/** What to do about an empty required field, in words for that field. */
function requiredMessage(t: Translate, field: ProviderFieldDef, providerType: string): string {
  switch (field.name) {
    case "api_key":
      return t("provider_form_api_key_required");
    case "endpoint":
      return t("provider_form_endpoint_required", {
        example: providerFieldPlaceholder(t, "endpoint", providerType)
      });
    case "api_version":
      return t("provider_form_api_version_required");
    case "deployment_name":
      return t("provider_form_deployment_name_required");
    default:
      return t("provider_form_field_required");
  }
}

/** The focus key of a secret field's confirmation input (see useFieldFocus). */
export const confirmationKey = (name: string) => `${name}:confirmation`;

/**
 * Where a provider field is wrong, as the key of the input to focus: the
 * field itself, or its confirmation for a secret. Null when it is fine.
 */
export function providerFieldProblem(
  field: ProviderFieldDef,
  value: string,
  confirmation: string
): string | null {
  if (field.secret) {
    const problem = confirmedSecretProblem({
      value,
      confirmation,
      isRequired: field.required
    });
    if (problem === "required") return field.name;
    return problem === "mismatch" ? confirmationKey(field.name) : null;
  }
  return field.required && value.trim() === "" ? field.name : null;
}

/**
 * Fields a form moves focus to by key: the first invalid one after a submit
 * (WCAG 3.3.1), or a field that replaced the control that had focus. A key
 * can name an input, or a group whose first input then takes focus.
 */
export function useFieldFocus() {
  const fields = useRef(new Map<string, HTMLElement>());
  // Stable, so effects can depend on it.
  return useMemo(
    () => ({
      ref: (key: string) => (element: HTMLElement | null) => {
        if (element) fields.current.set(key, element);
        else fields.current.delete(key);
      },
      /** Moves focus to the field; false when it is not on screen. */
      focus: (key: string): boolean => {
        const element = fields.current.get(key);
        const target =
          element instanceof HTMLInputElement
            ? element
            : element?.querySelector<HTMLInputElement>("input:not([disabled])");
        target?.focus();
        return Boolean(target);
      }
    }),
    []
  );
}

/**
 * One of a provider type's credential or config fields: a text field, or a
 * secret typed twice. Labels, hints and required messages come from the
 * field's name and the provider type, so every provider form says the same.
 */
export function ProviderField({
  field,
  providerType,
  value,
  confirmation = "",
  onValueChange,
  onConfirmationChange,
  showErrors,
  focus
}: {
  field: ProviderFieldDef;
  providerType: string;
  value: string;
  confirmation?: string;
  onValueChange: (value: string) => void;
  onConfirmationChange?: (value: string) => void;
  /** The form was submitted: show every problem at its field. */
  showErrors: boolean;
  focus: ReturnType<typeof useFieldFocus>;
}) {
  const t = useTranslations();
  const hint = providerFieldHint(t, field.name, field.required, providerType) || undefined;

  if (field.secret) {
    return (
      <ConfirmedSecretInput
        label={providerFieldLabel(t, field.name)}
        confirmLabel={providerConfirmFieldLabel(t, field.name)}
        description={hint}
        value={value}
        confirmation={confirmation}
        onValueChange={onValueChange}
        onConfirmationChange={onConfirmationChange ?? (() => {})}
        isRequired={field.required}
        // A provider's key is not the admin's own password.
        autoComplete="off"
        placeholder={providerFieldPlaceholder(t, field.name, providerType) || undefined}
        requiredMessage={requiredMessage(t, field, providerType)}
        mismatchMessage={
          field.name === "api_key"
            ? t("provider_form_api_key_mismatch")
            : t("provider_form_secret_mismatch")
        }
        showErrors={showErrors}
        valueRef={focus.ref(field.name)}
        confirmationRef={focus.ref(confirmationKey(field.name))}
      />
    );
  }

  const invalid = showErrors && field.required && value.trim() === "";
  return (
    <TextInput
      ref={focus.ref(field.name)}
      label={providerFieldLabel(t, field.name)}
      description={hint}
      value={value}
      onChange={onValueChange}
      isRequired={field.required}
      autoComplete="off"
      placeholder={providerFieldPlaceholder(t, field.name, providerType) || undefined}
      status={
        invalid ? { type: "error", message: requiredMessage(t, field, providerType) } : undefined
      }
    />
  );
}
