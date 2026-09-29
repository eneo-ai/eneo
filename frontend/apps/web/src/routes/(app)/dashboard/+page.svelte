<script lang="ts">
  import { IconProfile } from "@eneo/icons/profile";
  import { IconLogout } from "@eneo/icons/logout";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import * as Accordion from "$lib/components/ui/accordion/index.js";
  import { Accordion as AccordionPrimitive } from "bits-ui";
  import SpaceAccordionContent from "./SpaceAccordionContent.svelte";
  import { getAppContext } from "$lib/core/AppContext";
  import { onMount } from "svelte";

  import EneoWordMark from "$lib/assets/EneoWordMark.svelte";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";

  export let data;
  const { user } = getAppContext();

  // Consolidated filtering - spaces with any content (assistants, default_assistant for personal spaces, OR apps)
  const spacesWithContent = data.spaces.filter(
    (space) =>
      (space.applications?.assistants.count ?? 0) > 0 ||
      (space.personal && space.default_assistant != null) ||
      (space.applications?.apps.count ?? 0) > 0
  );

  let openSpaces = spacesWithContent.map((space) => space.id);

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
    <EneoWordMark class="text-brand-eneo my-2 h-5 w-20"></EneoWordMark>
    <DropdownMenu.Root>
      <DropdownMenu.Trigger>
        {#snippet child({ props })}
          <Button {...props} variant="ghost" size="icon" aria-label={m.user_menu()}>
            <IconProfile />
          </Button>
        {/snippet}
      </DropdownMenu.Trigger>
      <DropdownMenu.Content align="end">
        <DropdownMenu.Label class="font-normal">
          {m.logged_in_as()}<br /><span class="font-mono text-sm">{user.email}</span>
        </DropdownMenu.Label>
        <DropdownMenu.Separator />
        <!-- eslint-disable svelte/no-navigation-without-resolve -- localizeHref handles routing -->
        <DropdownMenu.Item variant="destructive">
          {#snippet child({ props })}
            <a {...props} href={localizeHref("/logout")} data-sveltekit-preload-data="false">
              <IconLogout />
              {m.logout()}
            </a>
          {/snippet}
        </DropdownMenu.Item>
        <!-- eslint-enable svelte/no-navigation-without-resolve -->
      </DropdownMenu.Content>
    </DropdownMenu.Root>
  </div>

  <Accordion.Root type="multiple" bind:value={openSpaces}>
    {#each spacesWithContent as space (space.id)}
      <Accordion.Item
        value={space.id}
        class="border-default mx-auto w-full max-w-[1400px] border-b"
      >
        <Accordion.Trigger
          level={2}
          class="hover:bg-hover-dimmer items-center rounded-none px-[1.4rem] py-4 font-mono text-sm uppercase hover:no-underline"
        >
          {space.personal ? m.personal() : m.dashboard_space_heading({ name: space.name })}
        </Accordion.Trigger>
        <AccordionPrimitive.Content class="pb-0 pl-4">
          <SpaceAccordionContent {space} />
        </AccordionPrimitive.Content>
      </Accordion.Item>
    {/each}
  </Accordion.Root>
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
