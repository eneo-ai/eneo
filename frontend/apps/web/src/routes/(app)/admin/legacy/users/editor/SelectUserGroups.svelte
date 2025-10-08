<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import { IconSelectedItem } from "@intric/icons/selected-item";
  import { Button } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric";
  import type { UserGroup } from "@intric/intric-js";
  import { createCombobox } from "@melt-ui/svelte";
  import { m } from "$lib/paraglide/messages";

  // Array of all currently selected collections
  export let selectedGroups: UserGroup[];
  export let userGroups: UserGroup[];
  export let user: { id: string };

  const intric = getIntric();

  const {
    elements: { menu, input, option },
    states: { open, inputValue, touchedInput, selected },
    helpers: { isSelected }
  } = createCombobox<UserGroup>({
    forceVisible: true,
    portal: null
  });

  async function removeFromGroup(group: UserGroup) {
    try {
      const success = await intric.userGroups.removeUser({ userGroup: group, user });
      if (success) {
        const index = selectedGroups.findIndex((current) => current.id === group.id);
        selectedGroups = selectedGroups.toSpliced(index, 1);
      }
    } catch (e) {
      alert(e);
      console.error(e);
    }
  }

  async function addToGroup() {
    if ($selected) {
      try {
        const group = $selected.value;
        // If the group is already added to the user, do not try to add it
        if (selectedGroups.find((curr) => curr.id === group.id)) {
          $selected = undefined;
          return;
        }

        const success = await intric.userGroups.addUser({ userGroup: group, user });
        if (success) {
          selectedGroups = [...selectedGroups, group];
          $selected = undefined;
        }
      } catch (e) {
        alert(e);
        console.error(e);
      }
    }
  }

  $: allGroups = (() => {
    const ids = selectedGroups.flatMap(({ id }) => id);
    return userGroups.filter(({ id }) => !ids.includes(id));
  })();

  $: filteredGroups = $touchedInput
    ? allGroups.filter(({ name }) => {
        const normalizedInput = $inputValue.toLowerCase();
        return name.toLowerCase().includes(normalizedInput);
      })
    : allGroups;

  $: if (!$open) {
    $inputValue = $selected?.label ?? "";
  }

  let inputElement: HTMLInputElement;
</script>

<div class="px-4 py-4">
  <div class="flex flex-col gap-1 pb-4">
    <div>
      <span class="pl-3 font-medium">{m.user_groups()}</span>
    </div>

    <div class="flex items-center justify-between gap-2">
      <div class="relative flex w-full">
        <input
          bind:this={inputElement}
          placeholder={m.select_user_group()}
          {...$input}
          use:input
          class="border-stronger bg-primary ring-default placeholder:text-secondary disabled:bg-secondary disabled:text-muted
        h-10 w-full items-center justify-between overflow-hidden rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2 disabled:shadow-none disabled:hover:ring-0"
        />
        <button
          on:click={() => {
            inputElement.focus();
            $open = true;
          }}
        >
          <IconChevronDown class="absolute top-2 right-4 h-6 w-6" />
        </button>
      </div>
      <Button variant="primary" disabled={$inputValue === ""} on:click={addToGroup}>{m.assign()}</Button>
    </div>
  </div>

  {#if selectedGroups.length > 0}
    <div class="border-stronger bg-secondary overflow-clip rounded-md border">
      {#each selectedGroups as selectedGroup (selectedGroup.id)}
        <div
          class="border-default hover:bg-primary flex w-full items-center justify-between border-b py-2 pr-2 pl-4 last-of-type:border-b-0"
        >
          <div>
            {selectedGroup.name}
          </div>
          <Button
            variant="destructive"
            on:click={() => {
              removeFromGroup(selectedGroup);
            }}>{m.remove()}</Button
          >
        </div>
      {/each}
    </div>
  {/if}
</div>

{#if $open}
  <ul
    class="shadow-bg-tertiary border-stronger bg-primary z-10 flex flex-col gap-1 overflow-y-auto rounded-lg border p-1 shadow-md focus:!ring-0"
    {...$menu}
    use:menu
  >
    <!-- svelte-ignore a11y-no-noninteractive-tabindex -->
    <div
      class="bg-primary text-primary flex max-h-full flex-col gap-0 overflow-y-auto"
      tabindex="0"
    >
      {#each filteredGroups as group (group.id)}
        <li
          {...$option({ value: group, label: group.name })}
          use:option
          class="hover:bg-tertiary flex items-center gap-1 rounded-md px-2 hover:cursor-pointer"
        >
          <IconSelectedItem class="{$isSelected(group) ? 'block' : 'hidden'} text-accent-default" />
          <div class="py-1">
            {group.name}
          </div>
        </li>
      {:else}
        <li
          class="flex items-center gap-1 rounded-md px-2 py-1 hover:cursor-pointer hover:bg-hover-default"
        >
          {m.no_results_found()}
        </li>
      {/each}
    </div>
  </ul>
{/if}
