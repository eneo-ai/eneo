<!--
  When using an external IDP the user's changes to their name will be overwritten on the next login.
  This interface makes only sense in cases where the external IDP does not dictate the user's name,
  e.g. when using username and password login.
-->

<script lang="ts">
  import { getAppContext } from "$lib/core/AppContext";
  import { Dialog, Button, Input } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  const { updateUserInfo } = getAppContext();

  export let firstName: string;
  export let lastName: string;
  export let displayName: string;

  // Needs to be defined as let first to not start out as "undefined"
  let displayNamePlaceholder = firstName + " " + lastName;
  $: displayNamePlaceholder = firstName + " " + lastName;

  // This check requires the placeholder to already be defined
  if (displayName === displayNamePlaceholder) {
    // The idea here is that we want the placeholder to be reactive, not the value
    displayName = "";
  }

  async function updateUser() {
    if (firstName === "" || lastName === "") return;

    try {
      await updateUserInfo({ firstName, lastName, displayName });
      $isOpen = false;
    } catch (e) {
      alert(m.error_updating_user_info());
    }
  }

  let isOpen: Dialog.OpenState;
</script>

<Dialog.Root bind:isOpen>
  <Dialog.Trigger asFragment let:trigger>
    <Button is={trigger} variant="outlined">{m.change_your_name()}</Button>
  </Dialog.Trigger>

  <Dialog.Content form width="medium">
    <Dialog.Title>{m.change_your_name()}</Dialog.Title>

    <Dialog.Section>
      <Input.Text
        bind:value={firstName}
        label={m.first_name()}
        description={m.first_name_description()}
        maxlength="200"
        type="text"
        required
        class="border-dimmer hover:bg-hover-dimmer justify-between border-b px-4 py-4"
      ></Input.Text>

      <Input.Text
        bind:value={lastName}
        label={m.last_name()}
        required
        maxlength="200"
        type="text"
        class="border-dimmer hover:bg-hover-dimmer border-b px-4 py-4"
      ></Input.Text>

      <Input.Text
        bind:value={displayName}
        label={m.full_name()}
        description={m.full_name_description()}
        placeholder={displayNamePlaceholder}
        maxlength="200"
        type="text"
        class="border-dimmer hover:bg-hover-dimmer border-b px-4 py-4"
      ></Input.Text>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>

      <Button variant="primary" on:click={updateUser}>{m.save_changes()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
