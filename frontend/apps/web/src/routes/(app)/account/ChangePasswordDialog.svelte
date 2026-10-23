<script lang="ts">
  import { Button } from "$lib/components/ui/button";
  import * as Dialog from "$lib/components/ui/dialog";
  import type { AvailablePasswordChangeCapability } from "$lib/features/auth/passwordChange";
  import PasswordChangeForm from "$lib/features/auth/components/PasswordChangeForm.svelte";
  import { m } from "$lib/paraglide/messages";

  let { capability, username } = $props<{
    capability: AvailablePasswordChangeCapability;
    username: string;
  }>();

  let open = $state(false);
  let form = $state<PasswordChangeForm | null>(null);
  // Mirrors `open` for the form's late results without tracking it reactively.
  let dialogIsOpen = false;

  function handleOpenChange(next: boolean) {
    dialogIsOpen = next;
    open = next;
    if (!next) form?.reset();
  }
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

    <PasswordChangeForm bind:this={form} {capability} {username} isActive={() => dialogIsOpen}>
      {#snippet footer({ pending })}
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
      {/snippet}
    </PasswordChangeForm>
  </Dialog.Content>
</Dialog.Root>
