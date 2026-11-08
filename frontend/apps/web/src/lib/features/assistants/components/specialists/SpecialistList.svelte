<!--
    Copyright (c) 2026 Sundsvalls Kommun
-->

<script lang="ts">
  import { IconAssistant } from "@eneo/icons/assistant";
  import { IconTrash } from "@eneo/icons/trash";
  import type { Assistant } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import SpecialistAddDialog from "./SpecialistAddDialog.svelte";
  import SpecialistEditDialog from "./SpecialistEditDialog.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";

  type Specialist = NonNullable<Assistant["specialists"]>[number];
  type Props = {
    specialists: NonNullable<Assistant["specialists"]>;
    /** Assistants that can never be specialists here, such as the assistant itself. */
    excludeIds?: string[];
  };

  let { specialists = $bindable([]), excludeIds = [] }: Props = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const availableSpecialists: Specialist[] = $derived.by(() => {
    return $currentSpace.applications.assistants
      .filter(
        ({ id }) => !excludeIds.includes(id) && !specialists.some(({ id: _id }) => id === _id)
      )
      .map(({ name, id, description }) => {
        return {
          id,
          handle: name,
          default_description: description ?? null,
          user_description: null
        };
      });
  });

  function updateSpecialist(updated: Specialist) {
    specialists = specialists.map((current) => (current.id === updated.id ? updated : current));
  }

  function addSpecialist(specialist: Specialist) {
    // Reassign so the bound editor store sees the change.
    specialists = [...specialists, specialist];
  }

  function removeSpecialist(specialist: { id: string }) {
    specialists = specialists.filter(({ id }) => id !== specialist.id);
  }
</script>

<ul class="flex flex-col" aria-label={m.specialists()}>
  {#each specialists as specialist (specialist.id)}
    <li class="item">
      <IconAssistant></IconAssistant>
      <span class="truncate px-2">
        {specialist.handle}
      </span>
      <div class="flex-grow"></div>
      <SpecialistEditDialog {specialist} {updateSpecialist}></SpecialistEditDialog>
      <Button
        variant="destructive"
        size="icon"
        aria-label={m.remove_specialist()}
        onclick={() => {
          removeSpecialist(specialist);
        }}><IconTrash /></Button
      >
    </li>
  {/each}
</ul>

<div class="h-2"></div>

<SpecialistAddDialog {addSpecialist} {availableSpecialists}></SpecialistAddDialog>

<style lang="postcss">
  @reference "@eneo/ui/styles";
  .item {
    @apply border-default bg-primary hover:bg-hover-dimmer flex h-16 w-full items-center gap-2 border-b px-4;
  }
</style>
