<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { writable, type Writable } from "svelte/store";
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
  export let isOpen: Writable<boolean> = writable(false);

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

<Dialog.Root bind:open={$isOpen}>
  {#if includeTrigger}
    <Dialog.Trigger>
      {#snippet child({ props })}
        <Button {...props}>{m.create_space()}</Button>
      {/snippet}
    </Dialog.Trigger>
  {/if}
  <Dialog.Content class={dialogLayout.content("medium")} closeLabel={m.close()}>
    <form class="contents" on:submit|preventDefault={createSpace}>
      <Dialog.Header class={dialogLayout.header}>
        <Dialog.Title>{m.create_new_space()}</Dialog.Title>
      </Dialog.Header>

      <div class={dialogLayout.body}>
        <div class={dialogLayout.section}>
          <Field.Field class="hover:bg-hover-dimmer px-4 py-4">
            <Field.Label for={nameId}>
              {m.name()}
              <span class="text-muted font-normal" aria-hidden="true">({m.required()})</span>
            </Field.Label>
            <Input id={nameId} bind:value={newSpaceName} required />
          </Field.Field>
        </div>
      </div>

      <Dialog.Footer class={dialogLayout.footer}>
        <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>
        <Button type="submit">{isCreatingSpace ? m.creating() : m.create_space()}</Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
