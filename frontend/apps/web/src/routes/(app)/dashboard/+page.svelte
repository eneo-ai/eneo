<script lang="ts">
  import { IconChevronRight } from "@intric/icons/chevron-right";
  import { IconProfile } from "@intric/icons/profile";
  import { IconLogout } from "@intric/icons/logout";
  import { Button, Dropdown } from "@intric/ui";
  import SpaceAccordionContent from "./SpaceAccordionContent.svelte";
  import { getAppContext } from "$lib/core/AppContext";
  import { createAccordion } from "@melt-ui/svelte";
  import { slide } from "svelte/transition";
  import { onMount } from "svelte";

  import EneoWordMark from "$lib/assets/EneoWordMark.svelte";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import SelectTheme from "$lib/components/SelectTheme.svelte";

  export let data;
  const { user } = getAppContext();

  // Consolidated filtering - spaces with any content (assistants OR apps)
  const spacesWithContent = data.spaces.filter(
    (space) => space.applications.assistants.count > 0 || space.applications.apps.count > 0
  );

  const {
    elements: { content, item, trigger, root },
    helpers: { isSelected }
  } = createAccordion({
    multiple: true,
    defaultValue: spacesWithContent.map((space) => space.id)
  });

  let div: HTMLDivElement;
  const scrollKey = "__dashboard__scroll__";
  onMount(() => {
    const scrollY = parseInt(sessionStorage.getItem(scrollKey) ?? "0");
    if (div) {
      div.scrollTo({
        top: scrollY,
        behavior: "instant"
      });
    }
  });
</script>

<svelte:head>
  <title>Eneo.ai – {m.dashboard()}</title>
</svelte:head>

<div
  class="outer bg-primary max-h-full w-full flex-col overflow-y-auto"
  bind:this={div}
  on:scroll={() => {
    sessionStorage.setItem(scrollKey, div.scrollTop.toString());
  }}
>
  <div
    class="bg-frosted-glass-primary sticky top-0 z-10 flex items-center justify-between p-4 py-2.5"
  >
    <EneoWordMark class="text-brand-intric my-2 h-5 w-20"></EneoWordMark>
    <Dropdown.Root>
      <Dropdown.Trigger let:trigger asFragment>
        <Button is={trigger} padding="icon">
          <IconProfile />
        </Button>
      </Dropdown.Trigger>
      <Dropdown.Menu let:item>
        <div class="p-2">
          {m.logged_in_as()}<br /><span class="font-mono text-sm">{user.email}</span>
        </div>
        <div class="border-default my-1 border-b"></div>
        <div class="p-2">
          <SelectTheme></SelectTheme>
        </div>
        <div class="border-default my-1 border-b"></div>
        <Button is={item} variant="destructive" href={localizeHref("/logout")} padding="icon-leading">
          <IconLogout />
          {m.logout()}</Button
        >
      </Dropdown.Menu>
    </Dropdown.Root>
  </div>

  <div {...$root}>
    {#each spacesWithContent as space (space.id)}
      <div class="mx-auto max-w-[1400px]" {...$item(space.id)} use:item>
        <!-- Level 1: Space Trigger -->
        <button
          class="hover:bg-hover-dimmer col-span-2 flex w-full items-center justify-between px-[1.4rem] py-4 font-mono text-sm uppercase md:col-span-3 lg:col-span-4"
          {...$trigger(space.id)}
          use:trigger
        >
          <span>
            {space.personal ? "Personal" : `Space: ${space.name}`}
          </span>

          <IconChevronRight
            class={$isSelected(space.id) ? "rotate-90 transition-all" : "transition-all"}
          ></IconChevronRight>
        </button>

        <!-- Level 1: Space Content (contains Level 2 accordion) -->
        {#if $isSelected(space.id)}
          <div
            class="pl-4"
            {...$content(space.id)}
            use:content
            transition:slide
          >
            <SpaceAccordionContent {space} />
          </div>
        {/if}
        <div class="border-default border-b"></div>
      </div>
    {/each}
  </div>
</div>

<style>
  @media (display-mode: standalone) {
    .outer {
      background-color: var(--background-primary);
      overflow-y: auto;
      margin: 0 0.5rem;
      border-radius: 1rem;
      box-shadow: 0 4px 10px 0px rgba(0, 0, 0, 0.1);
      max-height: 100%;
    }
  }

  @container (min-width: 1000px) {
    .outer {
      margin: 1.5rem;
      border-radius: 1rem;
      box-shadow: 0 4px 10px 0px rgba(0, 0, 0, 0.1);
      max-width: 1400px;
    }
  }
</style>
