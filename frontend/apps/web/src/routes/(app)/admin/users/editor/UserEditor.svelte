<script lang="ts">
  import { invalidate } from "$app/navigation";
  import SelectRole from "./SelectRole.svelte";
  import { type User } from "@intric/intric-js";
  import { Dialog, Button, Input } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric";
  import { getAdminUserCtx } from "../ctx";
  import { getAppContext } from "$lib/core/AppContext";
  import { m } from "$lib/paraglide/messages";

  const intric = getIntric();
  const { defaultRoles } = getAdminUserCtx();
  const { user: currentUser } = getAppContext();

  export let user: User;

  let userRole = user.predefined_roles.length > 0 ? user.predefined_roles[0] : defaultRoles[0];
  export let isOpen: Dialog.OpenState;

  async function updateUser() {
    if (!userRole) return;

    if (user.id === currentUser.id && !userRole.permissions.includes("admin")) {
      if (
        !confirm(
          m.role_change_admin_warning({ role: userRole.name })
        )
      ) {
        return;
      }
    }

    try {
      await intric.users.update({
        user: { id: user.id },
        update: { predefined_role: userRole }
      });
      invalidate("admin:users:load");
      $isOpen = false;
    } catch (e) {
      alert(e);
    }
  }
</script>

<Dialog.Root bind:isOpen>
  <Dialog.Content width="medium" form>
    <Dialog.Title>{m.edit_user()}</Dialog.Title>
    <Dialog.Description hidden>{m.edit_the_selected_user()}</Dialog.Description>

    <Dialog.Section>
      <Input.Text
        bind:value={user.email}
        label={m.email()}
        disabled
        type="email"
        class="border-default hover:bg-hover-dimmer border-b px-4 py-4"
      ></Input.Text>

      <SelectRole availableRoles={defaultRoles} bind:value={userRole}></SelectRole>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>

      <Button variant="primary" on:click={updateUser}>{m.save_changes()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
