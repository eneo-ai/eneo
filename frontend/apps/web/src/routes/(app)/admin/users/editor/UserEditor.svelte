<!--
    Copyright (c) 2024 Sundsvalls Kommun
-->

<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { tick, untrack } from "svelte";
  import type { Role, UserGroup } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button";
  import * as Dialog from "$lib/components/ui/dialog";
  import * as Field from "$lib/components/ui/field";
  import { Input } from "$lib/components/ui/input";
  import { Switch } from "$lib/components/ui/switch";
  import CopyButton from "$lib/components/CopyButton.svelte";
  import { generatePassword } from "@eneo/eneo-js/auth/password-generator";
  import { getEneo } from "$lib/core/Eneo";
  import { getAdminUserCtx } from "../ctx";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import { toastError } from "$lib/core/errors";
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
  let replacePassword = $state(false);
  /** The password Eneo set on save, shown once until the dialog closes. */
  let issuedPassword = $state<string | null>(null);
  let issuedPasswordInput = $state<HTMLInputElement | null>(null);
  let pending = $state(false);
  let groupPending = $state(false);
  const busy = $derived(pending || groupPending);

  function resetDraft() {
    username = user.username ?? "";
    email = user.email;
    userRoles = [...user.roles];
    replacePassword = false;
    issuedPassword = null;
  }

  // Reset on opening/closing or switching users, without erasing edits on a list refresh.
  $effect(() => {
    void open;
    void userId;
    untrack(resetDraft);
  });

  function handleOpenChange(next: boolean) {
    if (busy) return;
    const passwordWasShown = issuedPassword !== null;
    open = next;
    // Held back while a set password is on screen: a refreshed list may
    // re-render or drop this row, and the password with it.
    if (!next && passwordWasShown) invalidate("admin:users").catch(toastError);
  }

  async function saveUser(event: SubmitEvent) {
    event.preventDefault();
    if (busy) return;
    if (mode === "update" && !user.username) {
      toast.warning(m.cant_edit_user_without_username());
      return;
    }

    let password: string | null = null;
    if (mode === "create" || replacePassword) {
      try {
        // Drawn against the backend's own policy, so a policy change needs no change here.
        password = generatePassword(capability.policy);
      } catch {
        toast.error(m.admin_password_policy_unsatisfiable());
        return;
      }
    }

    pending = true;
    try {
      if (mode === "create" && password) {
        await eneo.users.create({ username, email, password, roles: userRoles });
      } else if (user.username) {
        const updated = await eneo.users.update({
          user: { username: user.username },
          update: {
            ...(email !== user.email ? { email } : {}),
            ...(username !== user.username ? { username } : {}),
            ...(password ? { password } : {}),
            roles: userRoles
          }
        });
        user = { ...user, ...updated };
      }
      if (password) {
        issuedPassword = password;
        await tick();
        issuedPasswordInput?.focus();
        return;
      }
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
      // A stray click must not throw away a password that is shown only once.
      if (busy || issuedPassword !== null) event.preventDefault();
    }}
  >
    {#if issuedPassword !== null}
      <Dialog.Header>
        <Dialog.Title id={`${id}-issued-title`}>
          {mode === "create" ? m.admin_user_created_title() : m.admin_password_replaced_title()}
        </Dialog.Title>
        <Dialog.Description id={`${id}-issued-hint`}>
          {m.admin_issued_password_handover({ email: user.email || email })}
          {m.admin_password_one_time_hint()}
        </Dialog.Description>
      </Dialog.Header>
      <Field.Field>
        <Field.Label for={`${id}-issued-password`}>{m.password()}</Field.Label>
        <div class="flex items-center gap-2">
          <Input
            bind:ref={issuedPasswordInput}
            id={`${id}-issued-password`}
            value={issuedPassword}
            readonly
            autocomplete="off"
            spellcheck={false}
            class="font-mono"
            aria-describedby={`${id}-issued-title ${id}-issued-hint`}
            onfocus={(event) => event.currentTarget.select()}
          />
          <CopyButton text={issuedPassword} label={m.copy()} showLabel variant="outline" />
        </div>
      </Field.Field>
      <Dialog.Footer>
        <Button onclick={() => handleOpenChange(false)}>{m.done()}</Button>
      </Dialog.Footer>
    {:else}
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
              {mode === "update"
                ? m.username_change_logout_hint()
                : m.unique_username_description()}
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
            {#if mode === "create"}
              <Field.Description>
                {m.admin_password_generated_hint()}
                {m.admin_password_one_time_hint()}
              </Field.Description>
            {:else}
              <Field.Field orientation="horizontal">
                <Field.Content>
                  <Field.Label for={`${id}-replace-password`}
                    >{m.admin_password_replace()}</Field.Label
                  >
                  <Field.Description id={`${id}-replace-password-hint`}>
                    {m.admin_password_replace_desc()}
                    {m.admin_password_one_time_hint()}
                  </Field.Description>
                </Field.Content>
                <Switch
                  id={`${id}-replace-password`}
                  checked={replacePassword}
                  onCheckedChange={(next) => (replacePassword = next)}
                  disabled={busy}
                  aria-describedby={`${id}-replace-password-hint`}
                />
              </Field.Field>
            {/if}
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
    {/if}
  </Dialog.Content>
</Dialog.Root>
