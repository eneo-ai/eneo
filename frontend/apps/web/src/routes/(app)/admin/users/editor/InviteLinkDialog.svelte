<script lang="ts">
  import { page } from "$app/stores";
  import { getAppContext } from "$lib/core/AppContext";
  import { Button, Dialog } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  const { tenant } = getAppContext();

  export let user: { email: string };
  export let isOpen: Dialog.OpenState;

  $: inviteLink = `${$page.url.origin}/invite/${tenant.zitadel_org_id}`;

  function copyInviteLink() {
    try {
      navigator.clipboard.writeText(inviteLink);
      copyButtonText = m.copied();
      setTimeout(() => {
        copyButtonText = m.copy_invite_link();
      }, 2000);
    } catch (error) {
      alert(m.could_not_copy_link());
    }
  }

  let copyButtonText = m.copy_invite_link();
</script>

<Dialog.Root bind:isOpen>
  <Dialog.Content width="medium" form>
    <Dialog.Title>{m.your_invite_link()}</Dialog.Title>

    <Dialog.Section>
      <div class="flex flex-col gap-4 p-4">
        <p>
          {m.send_email_link_instructions({ email: user.email })}
        </p>
        <p
          class="border-accent-default bg-accent-dimmer text-accent-stronger border-l-2 px-4 py-2 text-sm"
        >
          <span class="font-bold">{m.note()}</span> {m.signup_same_email_note()}
        </p>
        <div class="bg-primary flex items-center justify-between rounded-lg border p-1 shadow-sm">
          <span class="pl-2 font-mono">{inviteLink}</span>
          <Button variant="outlined" on:click={copyInviteLink}>{copyButtonText}</Button>
        </div>
      </div>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button variant="primary" is={close}>{m.done()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
