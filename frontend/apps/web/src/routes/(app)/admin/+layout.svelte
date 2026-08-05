<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { getAppContext } from "$lib/core/AppContext";
  import { dynamicColour } from "$lib/core/colours";
  import SpaceChip from "$lib/features/spaces/components/SpaceChip.svelte";
  import * as Sidebar from "$lib/components/ui/sidebar/index.js";
  import NavigationVersionInfo from "$lib/components/layout/Navigation/NavigationVersionInfo.svelte";
  import AdminMenu from "./AdminMenu.svelte";
  import { IconFeedback } from "@eneo/icons/feedback";
  import { m } from "$lib/paraglide/messages";
  import { IsMobile } from "$lib/hooks/is-mobile.svelte.js";

  const { tenant, featureFlags, environment } = getAppContext();
  const isMobile = new IsMobile();
  let navigationTrigger: HTMLButtonElement | null = null;

  // Mobile open state lives in descendant context, so this layout can only close it through the trigger.
  function closeMobileNavigation(event: MouseEvent) {
    if (isMobile.current && event.target instanceof Element && event.target.closest("a") !== null) {
      navigationTrigger?.click();
    }
  }
</script>

<div {...dynamicColour({ basedOn: "1" })} class="absolute inset-0 flex flex-grow justify-stretch">
  <Sidebar.Provider
    style="--sidebar-width: 17rem;"
    class="h-full min-h-0 w-full flex-grow justify-stretch"
  >
    <Sidebar.Root
      collapsible={isMobile.current ? "offcanvas" : "none"}
      class="border-default border-r-[0.5px]"
    >
      <Sidebar.Header
        class="border-default h-[4.25rem] flex-row items-center gap-3 border-b-[0.5px] px-[1.4rem] font-medium"
      >
        <SpaceChip
          space={{
            id: "1",
            name: tenant.display_name ?? m.your_organisation(),
            personal: false
          }}
        ></SpaceChip>
        <span class="text-primary flex-grow truncate pl-0.5 text-left">
          {tenant.display_name ?? m.your_organisation()}
        </span>
      </Sidebar.Header>

      <Sidebar.Content
        role="navigation"
        aria-label={m.admin_nav_aria()}
        class="py-1"
        onclick={closeMobileNavigation}
      >
        <AdminMenu></AdminMenu>
      </Sidebar.Content>

      <Sidebar.Footer class="border-default gap-0 border-t-[0.5px] p-0">
        {#if featureFlags.showHelpCenter}
          <!-- eslint-disable svelte/no-navigation-without-resolve -- external help center URL from environment config -->
          <a
            href={environment.helpCenterUrl}
            target="_blank"
            rel="noreferrer"
            class="text-muted hover:bg-hover-default hover:text-primary flex items-center justify-center gap-3 px-[1.45rem] py-2.5 tracking-[0.008rem] hover:font-medium hover:tracking-normal"
          >
            <span>{m.have_a_question()}</span>
            <IconFeedback />
          </a>
          <!-- eslint-enable svelte/no-navigation-without-resolve -->
        {/if}
        <NavigationVersionInfo />
      </Sidebar.Footer>
    </Sidebar.Root>

    <Sidebar.Trigger
      bind:ref={navigationTrigger}
      aria-label={m.admin_nav_toggle()}
      class="mt-2.5 ml-2.5 size-12 self-start md:hidden"
    />

    <slot />

    <div
      class="pointer-events-none absolute inset-0 -z-0 flex flex-grow shadow-xl md:left-[17rem]"
    ></div>
  </Sidebar.Provider>
</div>
