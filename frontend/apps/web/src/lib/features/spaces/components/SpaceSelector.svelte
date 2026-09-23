<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconChevronUpDown } from "@eneo/icons/chevron-up-down";
  import { IconSelectedItem } from "@eneo/icons/selected-item";
  import { IconSquare } from "@eneo/icons/square";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import type { Writable } from "svelte/store";
  import { getSpacesManager } from "../SpacesManager";
  import { fade } from "svelte/transition";
  import SpaceChip from "./SpaceChip.svelte";
  import CreateSpaceDialog from "./CreateSpaceDialog.svelte";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import { getAppContext } from "$lib/core/AppContext";

  export let showSelectPrompt = false;
  export let space:
    | {
        id: string;
        name: string;
        personal: boolean;
        organization?: boolean;
        icon_id?: string | null;
      }
    | undefined = undefined;

  const spaces = getSpacesManager();
  const {
    state: { currentSpace, accessibleSpaces }
  } = spaces;
  const { user } = getAppContext();
  const canCreateSharedSpace = user.hasPermission("shared_spaces");

  let open = false;
  let showCreateDialog: Writable<boolean>;

  $: displayedSpace = space ?? $currentSpace;
</script>

{#if (displayedSpace.personal || displayedSpace.organization) && !showSelectPrompt}
  <div
    class="group border-default relative flex h-[4.25rem] w-full items-center justify-start gap-3 border-b-[0.5px] pt-0.5 pr-5 pl-[1.4rem] font-medium"
  >
    <SpaceChip space={displayedSpace} />
    <span class="text-primary flex-grow truncate pl-0.5 text-left">
      {displayedSpace.personal ? m.personal_space() : m.organization_space()}
    </span>
  </div>
{:else}
  <DropdownMenu.Root bind:open>
    <DropdownMenu.Trigger disabled={displayedSpace.organization}>
      {#snippet child({ props })}
        <button
          {...props}
          aria-label={m.change_space_or_create()}
          class="group border-default hover:bg-accent-dimmer hover:text-accent-stronger relative flex h-[4.25rem] w-full cursor-pointer items-center justify-start gap-3 border-b-[0.5px] pt-0.5 pr-5 pl-[1.4rem] font-medium"
        >
          {#if showSelectPrompt}
            <div
              class="bg-dynamic-dimmer text-dynamic-stronger flex min-h-[1.6rem] min-w-[1.6rem] items-center justify-center rounded-md"
            >
              <IconSquare />
            </div>
            <span class="text-primary flex-grow truncate pl-0.5 text-left"
              >{m.select_a_space()}</span
            >
          {:else}
            <SpaceChip space={displayedSpace}></SpaceChip>
            <span class="text-primary flex-grow truncate pl-0.5 text-left">
              {displayedSpace.name}
            </span>
          {/if}
          {#if !displayedSpace.organization}
            <IconChevronUpDown class="text-muted group-hover:text-accent-stronger min-w-6" />
          {/if}
        </button>
      {/snippet}
    </DropdownMenu.Trigger>
    <DropdownMenu.Content
      align="start"
      class="space-selector-menu z-[80] flex min-w-[17rem] flex-col p-3"
    >
      <!-- eslint-disable svelte/no-navigation-without-resolve -- localizeHref handles routing -->
      <DropdownMenu.Item>
        {#snippet child({ props })}
          <a
            {...props}
            href={localizeHref("/spaces/list")}
            class="border-default text-secondary border-b pt-1 pr-3 pb-2.5 pl-6 font-mono text-[0.85rem] font-medium tracking-[0.015rem] outline-none hover:underline focus-visible:underline"
            >{m.your_spaces()}</a
          >
        {/snippet}
      </DropdownMenu.Item>

      <div class="relative max-h-[50vh] overflow-y-auto">
        {#each $accessibleSpaces.filter((s) => !s.personal && !s.organization) as space (space.id)}
          <DropdownMenu.Item>
            {#snippet child({ props })}
              <a
                {...props}
                href={localizeHref(`/spaces/${space.id}/overview`)}
                class="group border-default hover:bg-accent-dimmer hover:text-accent-stronger data-highlighted:bg-accent-dimmer data-highlighted:text-accent-stronger relative flex h-[4.25rem] w-full items-center justify-start gap-3 border-b pr-4 pl-5 outline-none last-of-type:border-b-0"
              >
                <SpaceChip {space} />
                <span class="flex-grow truncate text-left">{space.name}</span>
                <div class="text-accent-stronger ml-2 min-w-5">
                  {#if space.id === displayedSpace.id && !showSelectPrompt}
                    <IconSelectedItem />
                  {/if}
                </div>
              </a>
            {/snippet}
          </DropdownMenu.Item>
        {/each}
      </div>
      <!-- eslint-enable svelte/no-navigation-without-resolve -->
      {#if canCreateSharedSpace}
        <DropdownMenu.Item
          onSelect={() => {
            $showCreateDialog = true;
          }}
          class="border-default bg-accent-default text-on-fill hover:bg-accent-stronger focus:bg-accent-stronger focus:text-on-fill data-highlighted:bg-accent-stronger data-highlighted:text-on-fill mt-1 justify-center rounded-lg border py-2 shadow-md"
          >{m.create_new_space()}</DropdownMenu.Item
        >
      {/if}
    </DropdownMenu.Content>
  </DropdownMenu.Root>
{/if}

{#if open && !displayedSpace.organization}
  <div
    class="bg-overlay-dimmer fixed inset-0 z-[70]"
    transition:fade={{ duration: 200 }}
    aria-hidden="true"
  ></div>
{/if}

{#if canCreateSharedSpace && !displayedSpace.organization}
  <CreateSpaceDialog includeTrigger={false} forwardToNewSpace={true} bind:isOpen={showCreateDialog}
  ></CreateSpaceDialog>
{/if}

<style>
  :global(.space-selector-menu) {
    box-shadow:
      0px 10px 20px -10px rgba(0, 0, 0, 0.5),
      0px 30px 50px 0px rgba(0, 0, 0, 0.2);
  }
</style>
