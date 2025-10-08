<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, Dialog, Input } from "@intric/ui";
  import { getSpacesManager } from "../SpacesManager";
  import { goto } from "$app/navigation";
  import { m } from "$lib/paraglide/messages";

  const spaces = getSpacesManager();

  export let includeTrigger: boolean;
  export let forwardToNewSpace: boolean;
  export let isOpen: Dialog.OpenState | undefined = undefined;

  let newSpaceName = "";
  let isCreatingSpace = false;
</script>

<Dialog.Root bind:isOpen>
  {#if includeTrigger}
    <Dialog.Trigger let:trigger asFragment>
      <Button variant="primary" is={trigger}>{m.create_space()}</Button>
    </Dialog.Trigger>
  {/if}
  <Dialog.Content width="medium" form>
    <Dialog.Title>{m.create_new_space()}</Dialog.Title>

    <Dialog.Section>
      <Input.Text
        bind:value={newSpaceName}
        label={m.name()}
        required
        class="hover:bg-hover-dimmer px-4 py-4"
      ></Input.Text>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button
        variant="primary"
        on:click={async () => {
          if (newSpaceName === "") return;
          isCreatingSpace = true;
          const space = await spaces.createSpace({ name: newSpaceName });
          if (space) {
            $isOpen = false;
            newSpaceName = "";
            if (forwardToNewSpace) {
              goto(`/spaces/${space.id}`);
            }
          }
          isCreatingSpace = false;
        }}>{isCreatingSpace ? m.creating() : m.create_space()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
