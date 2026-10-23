<script lang="ts">
  import type { Snippet } from "svelte";
  import * as Sidebar from "$lib/components/ui/sidebar";
  import { getAppContext } from "$lib/core/AppContext";
  import { dynamicColour } from "$lib/core/colours";
  import { IsMobile } from "$lib/hooks/is-mobile.svelte.js";
  import { m } from "$lib/paraglide/messages";
  import MemberChip from "$lib/features/spaces/components/MemberChip.svelte";
  import AccountMenu from "./AccountMenu.svelte";

  let { children }: { children: Snippet } = $props();
  const { user } = getAppContext();
  const isMobile = new IsMobile();
  let navigationTrigger = $state<HTMLButtonElement | null>(null);

  function closeMobileNavigation(event: MouseEvent) {
    if (isMobile.current && event.target instanceof Element && event.target.closest("a")) {
      navigationTrigger?.click();
    }
  }
</script>

<div
  class="absolute inset-0 flex min-w-0 flex-grow justify-stretch"
  {...dynamicColour({ basedOn: user.email })}
>
  <Sidebar.Provider
    style="--sidebar-width: 17rem;"
    class="h-full min-h-0 min-w-0 w-full flex-grow justify-stretch"
  >
    <Sidebar.Root
      collapsible={isMobile.current ? "offcanvas" : "none"}
      class="border-default shrink-0 border-r-[0.5px]"
    >
      <Sidebar.Header
        class="border-default h-[4.25rem] shrink-0 flex-row items-center gap-3 border-b-[0.5px] px-[1.4rem] font-medium"
      >
        <MemberChip member={user} />
        <span class="text-primary min-w-0 flex-grow truncate pl-0.5">{user.email}</span>
      </Sidebar.Header>
      <Sidebar.Content onclick={closeMobileNavigation}>
        <AccountMenu />
      </Sidebar.Content>
    </Sidebar.Root>

    <div class="flex min-w-0 flex-1 flex-col">
      <Sidebar.Trigger
        bind:ref={navigationTrigger}
        aria-label={m.account_and_settings()}
        class="mt-2.5 ml-2.5 size-12 shrink-0 self-start md:hidden"
      />
      <div class="flex min-h-0 min-w-0 flex-1">
        {@render children()}
      </div>
    </div>

    <div
      class="pointer-events-none absolute inset-0 -z-0 flex flex-grow shadow-xl md:left-[17rem]"
    ></div>
  </Sidebar.Provider>
</div>
