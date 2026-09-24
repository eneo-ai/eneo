<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import NameDialog from "$lib/components/NameDialog.svelte";
  import { writable, type Writable } from "svelte/store";
  import { getEneo } from "$lib/core/Eneo";
  import { getSpacesManager } from "../SpacesManager";
  import { goto } from "$app/navigation";
  import { m } from "$lib/paraglide/messages";

  const eneo = getEneo();
  const spaces = getSpacesManager();

  export let includeTrigger: boolean;
  export let forwardToNewSpace: boolean;
  export let isOpen: Writable<boolean> = writable(false);

  async function createSpace(name: string) {
    const space = await eneo.spaces.create({ name });
    spaces.refreshSpaces();
    if (forwardToNewSpace) {
      const routeId = space.personal ? "personal" : space.id;
      // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic URL with new space route id
      goto(`/spaces/${routeId}/overview`);
    }
  }
</script>

{#snippet createTrigger({ props }: { props: Record<string, unknown> })}
  <Button {...props}>{m.create_space()}</Button>
{/snippet}

<NameDialog
  bind:open={$isOpen}
  title={m.create_new_space()}
  label={m.name()}
  submitLabel={m.create_space()}
  pendingLabel={m.creating()}
  width="medium"
  trigger={includeTrigger ? createTrigger : undefined}
  onSubmit={createSpace}
/>
