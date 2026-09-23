<script lang="ts">
  import { IconChevronUpDown } from "@eneo/icons/chevron-up-down";
  import { goto } from "$app/navigation";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Select as SelectPrimitive } from "bits-ui";
  import { fly } from "svelte/transition";
  import { quadInOut } from "svelte/easing";
  import { formatEmojiTitle } from "$lib/core/formatting/formatEmojiTitle";
  import SpaceChip from "$lib/features/spaces/components/SpaceChip.svelte";
  import { m } from "$lib/paraglide/messages";

  export let currentApp: { id: string; name: string };

  const {
    state: { currentSpace }
  } = getSpacesManager();

  function openApp(id: string) {
    // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic URL with space and app ids
    goto(`/spaces/${$currentSpace.routeId}/apps/${id}`);
  }
</script>

<Select.Root type="single" value={currentApp.id} onValueChange={openApp}>
  <SelectPrimitive.Trigger>
    {#snippet child({ props })}
      <button
        {...props}
        in:fly|global={{ x: -5, duration: parent ? 300 : 0, easing: quadInOut, opacity: 0.3 }}
        class="group text-primary hover:border-dimmer hover:bg-hover-default flex max-w-[calc(100%_-_1rem)] items-center justify-between gap-2 overflow-hidden rounded-lg border border-transparent py-0.5 pr-1 pl-2 text-[1.4rem] leading-normal font-extrabold"
      >
        <span class="truncate">{currentApp.name}</span>
        <!-- translate-y to make it look on the same line as the chevron in the space selector -->
        <IconChevronUpDown
          class="text-secondary group-hover:text-primary h-6 w-6 min-w-6 translate-y-[0.05rem]"
        ></IconChevronUpDown>
      </button>
    {/snippet}
  </SelectPrimitive.Trigger>
  <Select.Content align="start" class="min-w-[24vw]">
    <Select.Group>
      <Select.GroupHeading>{m.select_an_app()}</Select.GroupHeading>
      {#each $currentSpace.applications.apps as app (app.id)}
        <Select.Item value={app.id} label={app.name} class="min-h-12 gap-3">
          <SpaceChip space={{ ...app, personal: false }}></SpaceChip>
          <span class="truncate">{formatEmojiTitle(app.name)}</span>
        </Select.Item>
      {/each}
    </Select.Group>
  </Select.Content>
</Select.Root>
