<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { invalidate } from "$app/navigation";
  import SelectRole from "./SelectRole.svelte";
  import { makeEditable } from "$lib/core/editable";
  import { type Role, type UserGroup } from "@intric/intric-js";
  import { Dialog, Button, Input } from "@intric/ui";
  import SelectUserGroups from "./SelectUserGroups.svelte";
  import { getIntric } from "$lib/core/Intric";
  import { getAdminUserCtx } from "../ctx";
  import { m } from "$lib/paraglide/messages";

  const intric = getIntric();

  const { defaultRoles, customRoles, userGroups } = getAdminUserCtx();

  const createEmptyUser = () => {
    return {
      id: "",
      email: "",
      username: "",
      predefined_roles: [],
      roles: [],
      user_groups: []
    };
  };

  export let mode: "update" | "create" = "create";

  export let user: {
    id: string;
    username?: string | null | undefined;
    email: string;
    predefined_roles: Role[];
    roles: Role[];
    user_groups: UserGroup[];
  } = createEmptyUser();

  let userPassword = "";
  let username = user.username ?? "";
  let userRoles = user.predefined_roles.concat(user.roles);
  let defaultRolesIds = defaultRoles.flatMap((role) => role.id);

  let editableUser = makeEditable(user);

  let showDialog: Dialog.OpenState;

  function getRolesUpdate() {
    const updatedRoles = userRoles.reduce(
      (prev, curr) => {
        if (defaultRolesIds.includes(curr.id)) {
          prev.predefined_roles.push(curr);
        } else {
          prev.roles.push(curr);
        }
        return prev;
      },
      {
        roles: [] as Role[],
        predefined_roles: [] as Role[]
      }
    );
    return updatedRoles;
  }

  async function updateUser() {
    if (!user.username) {
      alert(m.cant_edit_user_without_username());
      return;
    }
    const update = {
      ...editableUser.getEdits(),
      password: userPassword === "" ? undefined : userPassword,
      username: username === user.username || username === "" ? undefined : username,
      ...getRolesUpdate()
    };
    try {
      await intric.users.update({
        user: { username: user.username },
        update
      });
      invalidate("admin:users:load");
      // Invalidate does not update the user and userPassword values in this component, so we need to update
      user = editableUser;
      userPassword = "";
      $showDialog = false;
    } catch (e) {
      alert(e);
    }
  }

  async function createUser() {
    if (username === "" || editableUser.email === "" || userPassword === "") {
      return;
    }
    const newUser = {
      ...editableUser,
      password: userPassword,
      ...getRolesUpdate(),
      username
    };
    try {
      await intric.users.create(newUser);
      editableUser.updateWithValue(createEmptyUser());
      userPassword = "";
      invalidate("admin:users:load");
      $showDialog = false;
    } catch (e) {
      alert(e);
    }
  }
</script>

<Dialog.Root bind:isOpen={showDialog}>
  {#if mode === "create"}
    <Dialog.Trigger asFragment let:trigger>
      <Button variant="primary" is={trigger}>{m.create_user()}</Button>
    </Dialog.Trigger>
  {:else}
    <Dialog.Trigger asFragment let:trigger>
      <Button is={trigger}>{m.edit()}</Button>
    </Dialog.Trigger>
  {/if}

  <Dialog.Content width="medium" form>
    {#if mode === "create"}
      <Dialog.Title>{m.create_a_new_user()}</Dialog.Title>
      <Dialog.Description hidden>{m.create_a_new_user()}</Dialog.Description>
    {:else}
      <Dialog.Title>{m.edit_user()}</Dialog.Title>
      <Dialog.Description hidden>{m.edit_the_selected_user()}</Dialog.Description>
    {/if}

    <Dialog.Section>
      <div class="hover:bg-hover-dimmer">
        <Input.Text
          bind:value={username}
          label={m.username()}
          description={m.unique_username_description()}
          required
          class="border-default px-4 py-4  {mode === 'create' ? 'border-b' : ''}"
        ></Input.Text>

        {#if mode === "update"}
          <p class="border-default text-secondary border-b pr-4 pb-4 pl-6 text-sm">
            {m.username_change_logout_hint()}
          </p>
        {/if}
      </div>

      <Input.Text
        bind:value={editableUser.email}
        label={m.email()}
        type="email"
        required
        class="border-default hover:bg-hover-dimmer border-b px-4 py-4"
      ></Input.Text>

      <Input.Text
        bind:value={userPassword}
        minlength="7"
        maxlength="100"
        label={m.password()}
        description={m.password_needs_7_chars()}
        required={mode === "create"}
        type="password"
        autocomplete="off"
        class="border-default hover:bg-hover-dimmer border-b px-4 py-4"
      ></Input.Text>

      <SelectRole {customRoles} {defaultRoles} bind:value={userRoles}></SelectRole>

      {#if mode === "update"}
        <SelectUserGroups bind:selectedGroups={editableUser.user_groups} {userGroups} {user}
        ></SelectUserGroups>
      {/if}
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      {#if mode === "create"}
        <Button variant="primary" on:click={createUser} type="submit">{m.create_user()}</Button>
      {:else}
        <Button variant="primary" on:click={updateUser}>{m.save_changes()}</Button>
      {/if}
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
