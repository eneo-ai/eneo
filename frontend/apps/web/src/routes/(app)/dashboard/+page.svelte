<script lang="ts">
  import { IconChevronRight } from "@intric/icons/chevron-right";
  import { IconProfile } from "@intric/icons/profile";
  import { IconLogout } from "@intric/icons/logout";
  import { Button, Dropdown } from "@intric/ui";
  import DashboardTile from "./DashboardTile.svelte";
  import { getAppContext } from "$lib/core/AppContext";
  import { createAccordion } from "@melt-ui/svelte";
  import { slide } from "svelte/transition";
  import { onMount } from "svelte";
  import EneoWordMark from "$lib/assets/EneoWordMark.svelte";

  export let data;
  const { user } = getAppContext();
  const spaces = data.spaces.filter((space) => space.applications.assistants.count > 0);

  const {
    elements: { content, item, trigger, root },
    helpers: { isSelected }
  } = createAccordion({
    multiple: true,
    defaultValue: spaces.map((space) => space.id)
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
  <title>Eneo.ai – Dashboard</title>
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
          Logged in as:<br /><span class="font-mono text-sm">{user.email}</span>
        </div>
        <div class="border-default my-1 border-b"></div>
        <Button is={item} variant="destructive" href="/logout" padding="icon-leading">
          <IconLogout />
          Logout</Button
        >
      </Dropdown.Menu>
    </Dropdown.Root>
  </div>

  <div {...$root}>
    {#each spaces as space (space.id)}
      <div class="mx-auto max-w-[1400px]" {...$item(space.id)} use:item>
        <button
          class="hover:bg-hover-dimmer col-span-2 flex w-full items-center justify-between px-[1.4rem] py-4 font-mono text-sm uppercase md:col-span-3 lg:col-span-4"
          {...$trigger(space.id)}
          use:trigger
        >
          <span>
            {space.personal ? "Personal assistants" : space.name}
          </span>

          <IconChevronRight
            class={$isSelected(space.id) ? "rotate-90 transition-all" : "transition-all"}
          ></IconChevronRight>
        </button>
        {#if $isSelected(space.id)}
          <div
            class="grid grid-cols-2 gap-4 px-5 pb-4 md:grid-cols-3 lg:grid-cols-4"
            {...$content(space.id)}
            use:content
            transition:slide
          >
            {#each space.applications.assistants.items as assistant (assistant.id)}
              <DashboardTile {assistant}></DashboardTile>
            {/each}
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
