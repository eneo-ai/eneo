<script lang="ts">
  import { invalidate } from "$app/navigation";
  import SelectRole from "./SelectRole.svelte";
  import { Dialog, Button, Input } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric";
  import { getAdminUserCtx } from "../ctx";
  import { getAppContext } from "$lib/core/AppContext";
  import InviteLinkDialog from "./InviteLinkDialog.svelte";
  import { m } from "$lib/paraglide/messages";

  const intric = getIntric();
  const { defaultRoles } = getAdminUserCtx();
  const { tenant } = getAppContext();

  let userRole = defaultRoles[0];
  let userEmail = "";
  let emailIsValid: boolean;
  let showDialog: Dialog.OpenState;
  let showInviteLink: Dialog.OpenState;

  async function inviteUser() {
    if (!userRole || !emailIsValid) return;

    try {
      await intric.users.invite({
        email: userEmail,
        predefined_role: userRole
      });
      invalidate("admin:users:load");
      $showDialog = false;
      $showInviteLink = true;
    } catch (e) {
      alert(e);
    }
  }
</script>

<InviteLinkDialog bind:isOpen={showInviteLink} user={{ email: userEmail }}></InviteLinkDialog>

<Dialog.Root bind:isOpen={showDialog}>
  <Dialog.Trigger asFragment let:trigger>
    <Button is={trigger} variant="primary">{m.create_invitation()}</Button>
  </Dialog.Trigger>

  <Dialog.Content width="medium" form>
    <Dialog.Title>{m.invite_a_new_user_to({ name: tenant.display_name || "" })}</Dialog.Title>

    <Dialog.Section>
      <Input.Text
        bind:isValid={emailIsValid}
        bind:value={userEmail}
        label={m.email()}
        required
        type="email"
        class="border-default hover:bg-hover-dimmer border-b px-4 py-4"
      ></Input.Text>

      <SelectRole availableRoles={defaultRoles} bind:value={userRole}></SelectRole>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="primary" on:click={inviteUser}>{m.create_invitation()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
