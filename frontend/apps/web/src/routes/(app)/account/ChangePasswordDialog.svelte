<script lang="ts">
  import { goto } from "$app/navigation";
  import { enhance } from "$app/forms";
  import { Button } from "$lib/components/ui/button";
  import * as Dialog from "$lib/components/ui/dialog";
  import * as Field from "$lib/components/ui/field";
  import { Input } from "$lib/components/ui/input";
  import {
    firstInvalidPasswordField,
    isCurrentPasswordChangeDialogSubmission,
    validatePasswordChange,
    type PasswordChangeActionFailure,
    type PasswordChangeCapability,
    type PasswordChangeFormError,
    type PasswordField,
    type PasswordFieldErrors,
    type PasswordValidationError
  } from "$lib/features/auth/passwordChange";
  import { m } from "$lib/paraglide/messages";
  import { Eye, EyeOff } from "lucide-svelte";
  import type { SubmitFunction } from "./$types";

  type AvailablePasswordCapability = Extract<
    PasswordChangeCapability,
    { source: "eneo" | "zitadel" }
  >;

  let { capability, username } = $props<{
    capability: AvailablePasswordCapability;
    username: string;
  }>();

  let open = $state(false);
  let pending = $state(false);
  let currentPassword = $state("");
  let newPassword = $state("");
  let confirmPassword = $state("");
  let showCurrentPassword = $state(false);
  let showNewPassword = $state(false);
  let showConfirmPassword = $state(false);
  let fieldErrors = $state<PasswordFieldErrors>({});
  let formError = $state<PasswordChangeFormError | null>(null);
  // Request lifecycle marker only; it deliberately does not drive rendering.
  let dialogEpoch = 0;
  let dialogIsOpen = false;
  let currentPasswordInput = $state<HTMLInputElement | null>(null);
  let newPasswordInput = $state<HTMLInputElement | null>(null);
  let confirmPasswordInput = $state<HTMLInputElement | null>(null);
  let errorSummary = $state<HTMLDivElement | null>(null);

  const hasFieldErrors = $derived(Object.keys(fieldErrors).length > 0);

  function resetSensitiveState() {
    currentPassword = "";
    newPassword = "";
    confirmPassword = "";
    showCurrentPassword = false;
    showNewPassword = false;
    showConfirmPassword = false;
    fieldErrors = {};
    formError = null;
    pending = false;
  }

  function handleOpenChange(next: boolean) {
    dialogIsOpen = next;
    open = next;
    if (!next) {
      dialogEpoch += 1;
      resetSensitiveState();
    }
  }

  function validationMessage(error: PasswordValidationError): string {
    switch (error) {
      case "required":
        return m.password_field_required();
      case "current_password_incorrect":
        return m.current_password_incorrect();
      case "confirmation_mismatch":
        return m.passwords_dont_match();
      case "password_unchanged":
        return m.password_must_be_different();
      case "too_short":
        return m.password_policy_min_length({ min: capability.policy.minLength });
      case "too_long_bytes":
        return m.password_policy_max_bytes({ max: capability.policy.maxBytes ?? 0 });
      case "uppercase_required":
        return m.password_policy_uppercase();
      case "lowercase_required":
        return m.password_policy_lowercase();
      case "number_required":
        return m.password_policy_number();
      case "symbol_required":
        return m.password_policy_symbol();
      case "policy_rejected":
        return m.password_policy_rejected();
    }
  }

  function formErrorMessage(error: PasswordChangeFormError): string {
    switch (error) {
      case "not_available":
        return m.password_change_not_available();
      case "provider_rejected":
        return m.password_change_provider_rejected();
      case "rate_limited":
        return m.password_change_rate_limited();
      case "request_failed":
        return m.password_change_failed();
    }
  }

  function inputFor(field: PasswordField): HTMLInputElement | null {
    if (field === "currentPassword") return currentPasswordInput;
    if (field === "newPassword") return newPasswordInput;
    return confirmPasswordInput;
  }

  function focusFailure() {
    queueMicrotask(() => {
      const invalidField = firstInvalidPasswordField(fieldErrors);
      if (invalidField) inputFor(invalidField)?.focus();
      else errorSummary?.focus();
    });
  }

  function isValidationError(value: unknown): value is PasswordValidationError {
    return [
      "required",
      "current_password_incorrect",
      "confirmation_mismatch",
      "password_unchanged",
      "policy_rejected",
      "too_short",
      "too_long_bytes",
      "uppercase_required",
      "lowercase_required",
      "number_required",
      "symbol_required"
    ].includes(String(value));
  }

  function isFormError(value: unknown): value is PasswordChangeFormError {
    return ["not_available", "provider_rejected", "rate_limited", "request_failed"].includes(
      String(value)
    );
  }

  function parseActionFailure(value: unknown): PasswordChangeActionFailure {
    if (typeof value !== "object" || value === null) return { formError: "request_failed" };
    const candidate = value as Record<string, unknown>;
    const parsedFormError = isFormError(candidate.formError) ? candidate.formError : undefined;
    let parsedFieldErrors: PasswordFieldErrors | undefined;

    if (typeof candidate.fieldErrors === "object" && candidate.fieldErrors !== null) {
      const candidateFields = candidate.fieldErrors as Record<string, unknown>;
      const parsedFields: PasswordFieldErrors = {};
      for (const field of ["currentPassword", "newPassword", "confirmPassword"] as const) {
        if (isValidationError(candidateFields[field])) parsedFields[field] = candidateFields[field];
      }
      if (Object.keys(parsedFields).length > 0) parsedFieldErrors = parsedFields;
    }

    return parsedFormError || parsedFieldErrors
      ? { formError: parsedFormError, fieldErrors: parsedFieldErrors }
      : { formError: "request_failed" };
  }

  const enhancePasswordForm: SubmitFunction = ({ formData, cancel }) => {
    currentPassword = String(formData.get("currentPassword") ?? "");
    newPassword = String(formData.get("newPassword") ?? "");
    confirmPassword = String(formData.get("confirmPassword") ?? "");
    fieldErrors = validatePasswordChange(
      { currentPassword, newPassword, confirmPassword },
      capability
    );
    formError = null;

    if (Object.keys(fieldErrors).length > 0) {
      cancel();
      focusFailure();
      return;
    }

    const submittedInDialogEpoch = dialogEpoch;
    pending = true;
    return async ({ result }) => {
      if (result.type === "redirect") {
        resetSensitiveState();
        // eslint-disable-next-line svelte/no-navigation-without-resolve -- server-owned same-origin redirect
        await goto(result.location);
        return;
      }

      if (
        !isCurrentPasswordChangeDialogSubmission(dialogIsOpen, dialogEpoch, submittedInDialogEpoch)
      ) {
        return;
      }

      pending = false;
      if (result.type === "failure") {
        const data = result.data as Record<string, unknown> | undefined;
        const failure = parseActionFailure(data?.passwordChange);
        fieldErrors = failure.fieldErrors ?? {};
        formError = failure.formError ?? null;
        if (fieldErrors.currentPassword === "current_password_incorrect") {
          currentPassword = "";
        }
      } else {
        fieldErrors = {};
        formError = "request_failed";
      }
      focusFailure();
    };
  };
</script>

<Dialog.Root {open} onOpenChange={handleOpenChange}>
  <Dialog.Trigger>
    {#snippet child({ props })}
      <Button {...props} variant="outline">{m.change_password()}</Button>
    {/snippet}
  </Dialog.Trigger>

  <Dialog.Content class="sm:max-w-lg" closeLabel={m.close()}>
    <Dialog.Header>
      <Dialog.Title>{m.change_password()}</Dialog.Title>
      <Dialog.Description>{m.change_password_description()}</Dialog.Description>
    </Dialog.Header>

    <form
      method="POST"
      action="?/changePassword"
      use:enhance={enhancePasswordForm}
      class="space-y-4"
      novalidate
    >
      <!-- Password managers need the account identifier beside password fields. -->
      <input
        class="sr-only"
        tabindex="-1"
        aria-hidden="true"
        name="username"
        autocomplete="username"
        value={username}
        readonly
      />

      {#if formError || hasFieldErrors}
        <div
          bind:this={errorSummary}
          role="alert"
          tabindex="-1"
          class="border-negative-default bg-negative-dimmer text-negative-stronger rounded-lg border p-3 text-sm outline-none"
        >
          {formError ? formErrorMessage(formError) : m.password_check_marked_fields()}
        </div>
      {/if}

      <Field.Group>
        <Field.Field data-invalid={fieldErrors.currentPassword ? "true" : undefined}>
          <Field.Label for="current-password">{m.current_password()}</Field.Label>
          <div class="relative">
            <Input
              bind:ref={currentPasswordInput}
              bind:value={currentPassword}
              id="current-password"
              name="currentPassword"
              type={showCurrentPassword ? "text" : "password"}
              autocomplete="current-password"
              required
              aria-invalid={fieldErrors.currentPassword ? "true" : undefined}
              aria-describedby={fieldErrors.currentPassword ? "current-password-error" : undefined}
              disabled={pending}
              class="pr-10"
            />
            <button
              type="button"
              class="text-muted hover:text-default focus-visible:ring-ring absolute top-1/2 right-1 flex size-7 -translate-y-1/2 items-center justify-center rounded-md outline-none focus-visible:ring-2"
              aria-label={showCurrentPassword ? m.hide_password() : m.show_password()}
              aria-pressed={showCurrentPassword}
              onclick={() => (showCurrentPassword = !showCurrentPassword)}
              disabled={pending}
            >
              {#if showCurrentPassword}<EyeOff aria-hidden="true" />{:else}<Eye
                  aria-hidden="true"
                />{/if}
            </button>
          </div>
          {#if fieldErrors.currentPassword}
            <Field.Error id="current-password-error">
              {validationMessage(fieldErrors.currentPassword)}
            </Field.Error>
          {/if}
        </Field.Field>

        <Field.Field data-invalid={fieldErrors.newPassword ? "true" : undefined}>
          <Field.Label for="new-password">{m.new_password()}</Field.Label>
          <div class="relative">
            <Input
              bind:ref={newPasswordInput}
              bind:value={newPassword}
              id="new-password"
              name="newPassword"
              type={showNewPassword ? "text" : "password"}
              autocomplete="new-password"
              required
              aria-invalid={fieldErrors.newPassword ? "true" : undefined}
              aria-describedby={fieldErrors.newPassword
                ? "password-policy new-password-error"
                : "password-policy"}
              disabled={pending}
              class="pr-10"
            />
            <button
              type="button"
              class="text-muted hover:text-default focus-visible:ring-ring absolute top-1/2 right-1 flex size-7 -translate-y-1/2 items-center justify-center rounded-md outline-none focus-visible:ring-2"
              aria-label={showNewPassword ? m.hide_password() : m.show_password()}
              aria-pressed={showNewPassword}
              onclick={() => (showNewPassword = !showNewPassword)}
              disabled={pending}
            >
              {#if showNewPassword}<EyeOff aria-hidden="true" />{:else}<Eye
                  aria-hidden="true"
                />{/if}
            </button>
          </div>
          {#if fieldErrors.newPassword}
            <Field.Error id="new-password-error">
              {validationMessage(fieldErrors.newPassword)}
            </Field.Error>
          {/if}
        </Field.Field>

        <Field.Field data-invalid={fieldErrors.confirmPassword ? "true" : undefined}>
          <Field.Label for="confirm-password">{m.confirm_new_password()}</Field.Label>
          <div class="relative">
            <Input
              bind:ref={confirmPasswordInput}
              bind:value={confirmPassword}
              id="confirm-password"
              name="confirmPassword"
              type={showConfirmPassword ? "text" : "password"}
              autocomplete="new-password"
              required
              aria-invalid={fieldErrors.confirmPassword ? "true" : undefined}
              aria-describedby={fieldErrors.confirmPassword ? "confirm-password-error" : undefined}
              disabled={pending}
              class="pr-10"
            />
            <button
              type="button"
              class="text-muted hover:text-default focus-visible:ring-ring absolute top-1/2 right-1 flex size-7 -translate-y-1/2 items-center justify-center rounded-md outline-none focus-visible:ring-2"
              aria-label={showConfirmPassword ? m.hide_password() : m.show_password()}
              aria-pressed={showConfirmPassword}
              onclick={() => (showConfirmPassword = !showConfirmPassword)}
              disabled={pending}
            >
              {#if showConfirmPassword}<EyeOff aria-hidden="true" />{:else}<Eye
                  aria-hidden="true"
                />{/if}
            </button>
          </div>
          {#if fieldErrors.confirmPassword}
            <Field.Error id="confirm-password-error">
              {validationMessage(fieldErrors.confirmPassword)}
            </Field.Error>
          {/if}
        </Field.Field>
      </Field.Group>

      <div id="password-policy" class="bg-subtle text-secondary rounded-lg p-3 text-sm">
        <p class="text-default font-medium">{m.password_policy_intro()}</p>
        <ul class="mt-1 list-inside list-disc">
          {#if capability.policy.minLength > 0}
            <li>{m.password_policy_min_length({ min: capability.policy.minLength })}</li>
          {/if}
          {#if capability.policy.maxBytes !== null}
            <li>{m.password_policy_max_bytes({ max: capability.policy.maxBytes })}</li>
          {/if}
          {#if capability.policy.requiresUppercase}<li>{m.password_policy_uppercase()}</li>{/if}
          {#if capability.policy.requiresLowercase}<li>{m.password_policy_lowercase()}</li>{/if}
          {#if capability.policy.requiresNumber}<li>{m.password_policy_number()}</li>{/if}
          {#if capability.policy.requiresSymbol}<li>{m.password_policy_symbol()}</li>{/if}
        </ul>
      </div>

      <p class="text-secondary text-sm">{m.password_change_sign_out_notice()}</p>

      <Dialog.Footer>
        <Dialog.Close>
          {#snippet child({ props })}
            <Button {...props} variant="outline" disabled={pending}>{m.cancel()}</Button>
          {/snippet}
        </Dialog.Close>
        <Button type="submit" disabled={pending}>
          {pending ? m.changing_password() : m.change_password()}
        </Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
