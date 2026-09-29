<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { untrack } from "svelte";
  import type { Role, UserGroup } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button";
  import * as Dialog from "$lib/components/ui/dialog";
  import * as Field from "$lib/components/ui/field";
  import { Input } from "$lib/components/ui/input";
  import { getEneo } from "$lib/core/Eneo";
  import { getAdminUserCtx } from "../ctx";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import { toastError } from "$lib/core/errors";
  import {
    validateNewPasswordPair,
    type NewPasswordFieldErrors,
    type PasswordValidationError
  } from "$lib/features/auth/passwordChange";
  import PasswordPolicyChecklist from "$lib/features/auth/PasswordPolicyChecklist.svelte";
  import SelectRole from "./SelectRole.svelte";
  import SelectUserGroups from "./SelectUserGroups.svelte";

  type EditableUser = {
    id: string;
    username?: string | null;
    email: string;
    roles: Role[];
    user_groups: UserGroup[];
  };

  let {
    mode = "create",
    hideTrigger = false,
    user = $bindable<EditableUser>({ id: "", email: "", roles: [], user_groups: [] }),
    open = $bindable(false)
  }: {
    mode?: "update" | "create";
    hideTrigger?: boolean;
    user?: EditableUser;
    open?: boolean;
  } = $props();

  const eneo = getEneo();
  const admin = getAdminUserCtx();
  const allRoles = $derived(admin.roles);
  const userGroups = $derived(admin.userGroups);
  const capability = $derived(admin.passwordCapability);
  const id = $props.id();
  const userId = $derived(user.id);
  let username = $state("");
  let email = $state("");
  let userRoles = $state<Role[]>([]);
  let newPassword = $state("");
  let confirmPassword = $state("");
  let submitted = $state(false);
  let pending = $state(false);
  let groupPending = $state(false);
  let passwordInput = $state<HTMLInputElement | null>(null);
  let confirmationInput = $state<HTMLInputElement | null>(null);
  const busy = $derived(pending || groupPending);
  const passwordErrors: NewPasswordFieldErrors = $derived(
    validateNewPasswordPair({ newPassword, confirmPassword }, capability, mode === "create")
  );
  const newPasswordError = $derived(submitted ? passwordErrors.newPassword : undefined);
  const confirmationError = $derived(
    submitted || confirmPassword ? passwordErrors.confirmPassword : undefined
  );

  function resetDraft() {
    username = user.username ?? "";
    email = user.email;
    userRoles = [...user.roles];
    newPassword = "";
    confirmPassword = "";
    submitted = false;
  }

  // Reset on opening/closing or switching users, without erasing edits on a list refresh.
  $effect(() => {
    void open;
    void userId;
    untrack(resetDraft);
  });

  function passwordErrorMessage(error: PasswordValidationError): string {
    if (error === "required") return m.password_field_required();
    if (error === "confirmation_mismatch") return m.passwords_dont_match();
    if (error === "too_long_bytes") {
      return m.password_policy_max_bytes({ max: capability.policy.maxBytes ?? 0 });
    }
    if (error === "uppercase_required") return m.password_policy_uppercase();
    if (error === "lowercase_required") return m.password_policy_lowercase();
    if (error === "number_required") return m.password_policy_number();
    if (error === "symbol_required") return m.password_policy_symbol();
    return m.password_policy_min_length({ min: capability.policy.minLength });
  }

  function handleOpenChange(next: boolean) {
    if (!busy) open = next;
  }

  async function saveUser(event: SubmitEvent) {
    event.preventDefault();
    if (busy) return;
    submitted = true;
    if (passwordErrors.newPassword || passwordErrors.confirmPassword) {
      if (passwordErrors.newPassword) passwordInput?.focus();
      else confirmationInput?.focus();
      return;
    }
    if (mode === "update" && !user.username) {
      toast.warning(m.cant_edit_user_without_username());
      return;
    }

    pending = true;
    try {
      if (mode === "create") {
        await eneo.users.create({ username, email, password: newPassword, roles: userRoles });
      } else if (user.username) {
        const updated = await eneo.users.update({
          user: { username: user.username },
          update: {
            ...(email !== user.email ? { email } : {}),
            ...(username !== user.username ? { username } : {}),
            ...(newPassword ? { password: newPassword } : {}),
            roles: userRoles
          }
        });
        user = { ...user, ...updated };
      }
      // Clear credentials and close even if refreshing the list subsequently fails.
      newPassword = "";
      confirmPassword = "";
      open = false;
      await invalidate("admin:users");
    } catch (error) {
      toastError(error);
    } finally {
      pending = false;
    }
  }
</script>

<Dialog.Root {open} onOpenChange={handleOpenChange}>
  {#if !hideTrigger}
    <Dialog.Trigger>
      {#snippet child({ props })}
        <Button {...props} variant={mode === "create" ? "default" : "outline"}>
          {mode === "create" ? m.create_user() : m.edit()}
        </Button>
      {/snippet}
    </Dialog.Trigger>
  {/if}
  <Dialog.Content
    class="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg"
    closeLabel={m.close()}
    showCloseButton={!busy}
    onEscapeKeydown={(event) => {
      if (busy) event.preventDefault();
    }}
    onInteractOutside={(event) => {
      if (busy) event.preventDefault();
    }}
  >
    <Dialog.Header>
      <Dialog.Title>{mode === "create" ? m.create_a_new_user() : m.edit_user()}</Dialog.Title>
      <Dialog.Description>
        {mode === "create" ? m.admin_create_user_description() : m.admin_edit_user_description()}
      </Dialog.Description>
    </Dialog.Header>

    <form onsubmit={saveUser} aria-busy={busy} class="space-y-6">
      <fieldset disabled={busy} class="space-y-5">
        <Field.Field>
          <Field.Label for={`${id}-username`}>{m.username()}</Field.Label>
          <Input
            id={`${id}-username`}
            name="username"
            bind:value={username}
            required
            autocomplete="off"
            aria-describedby={`${id}-username-hint`}
          />
          <Field.Description id={`${id}-username-hint`}>
            {mode === "update" ? m.username_change_logout_hint() : m.unique_username_description()}
          </Field.Description>
        </Field.Field>
        <Field.Field>
          <Field.Label for={`${id}-email`}>{m.email()}</Field.Label>
          <Input
            id={`${id}-email`}
            name="email"
            type="email"
            bind:value={email}
            required
            autocomplete="off"
          />
        </Field.Field>
        <SelectRole roles={allRoles} bind:value={userRoles} disabled={busy} />

        <Field.Set class="border-border border-t pt-5">
          <Field.Legend>{m.password()}</Field.Legend>
          <Field.Description id={`${id}-password-hint`}>
            {mode === "update" ? m.admin_password_optional_hint() : m.admin_password_create_hint()}
          </Field.Description>
          <Field.Group class="gap-4">
            <Field.Field data-invalid={!!newPasswordError}>
              <Field.Label for={`${id}-new-password`}>{m.new_password()}</Field.Label>
              <Input
                bind:ref={passwordInput}
                id={`${id}-new-password`}
                name="new-password"
                type="password"
                value={newPassword}
                oninput={(event) => (newPassword = event.currentTarget.value)}
                autocomplete="new-password"
                spellcheck={false}
                aria-required={mode === "create" || !!confirmPassword}
                aria-invalid={!!newPasswordError}
                aria-describedby={`${id}-password-hint ${id}-password-policy${newPasswordError ? ` ${id}-new-password-error` : ""}`}
              />
              {#if newPasswordError}
                <Field.Error id={`${id}-new-password-error`}
                  >{passwordErrorMessage(newPasswordError)}</Field.Error
                >
              {/if}
            </Field.Field>
            <Field.Field data-invalid={!!confirmationError}>
              <Field.Label for={`${id}-confirm-password`}>{m.confirm_new_password()}</Field.Label>
              <Input
                bind:ref={confirmationInput}
                id={`${id}-confirm-password`}
                name="confirm-password"
                type="password"
                value={confirmPassword}
                oninput={(event) => (confirmPassword = event.currentTarget.value)}
                autocomplete="new-password"
                spellcheck={false}
                aria-required={mode === "create" || !!newPassword}
                aria-invalid={!!confirmationError}
                aria-describedby={`${id}-password-policy${confirmationError ? ` ${id}-confirm-password-error` : ""}`}
              />
              {#if confirmationError}
                <Field.Error id={`${id}-confirm-password-error`}
                  >{passwordErrorMessage(confirmationError)}</Field.Error
                >
              {/if}
            </Field.Field>
          </Field.Group>
          <PasswordPolicyChecklist
            id={`${id}-password-policy`}
            password={newPassword}
            {confirmPassword}
            {capability}
          />
        </Field.Set>
      </fieldset>

      {#if mode === "update"}
        <SelectUserGroups
          selectedGroups={user.user_groups}
          {userGroups}
          {user}
          disabled={pending}
          bind:pending={groupPending}
          onChanged={(groups) => {
            user = { ...user, user_groups: groups };
          }}
        />
      {/if}

      <Dialog.Footer>
        <Button variant="outline" disabled={busy} onclick={() => handleOpenChange(false)}
          >{m.cancel()}</Button
        >
        <Button type="submit" disabled={busy}>
          {pending ? m.saving() : mode === "create" ? m.create_user() : m.save_changes()}
        </Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
