<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, Dialog } from "@eneo/ui";
  import { useId } from "bits-ui";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { getSpacesManager } from "../SpacesManager";
  import { goto } from "$app/navigation";
  import { m } from "$lib/paraglide/messages";

  const spaces = getSpacesManager();
  const nameId = useId();

  export let includeTrigger: boolean;
  export let forwardToNewSpace: boolean;
  export let isOpen: Dialog.OpenState | undefined = undefined;

  let newSpaceName = "";
  let isCreatingSpace = false;

  async function createSpace() {
    if (newSpaceName === "") return;
    isCreatingSpace = true;
    try {
      const space = await spaces.createSpace({ name: newSpaceName });
      if (space) {
        $isOpen = false;
        newSpaceName = "";
        if (forwardToNewSpace) {
          const routeId = space.personal ? "personal" : space.id;
          // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic URL with new space route id
          await goto(`/spaces/${routeId}/overview`);
        }
      }
    } finally {
      isCreatingSpace = false;
    }
  }
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
      <Field.Field class="hover:bg-hover-dimmer px-4 py-4">
        <Field.Label for={nameId}>
          {m.name()}
          <span class="text-muted font-normal" aria-hidden="true">({m.required()})</span>
        </Field.Label>
        <Input id={nameId} bind:value={newSpaceName} required />
      </Field.Field>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="primary" on:click={createSpace}
        >{isCreatingSpace ? m.creating() : m.create_space()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
