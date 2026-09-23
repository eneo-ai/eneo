<script lang="ts">
  import type { Icon } from "@eneo/icons";
  import type { Component } from "svelte";

  export let href: string;
  export let isActive: boolean;
  export let icon: Icon | Component<{ class?: string }>;
  export let label: string;
</script>

<!-- eslint-disable svelte/no-navigation-without-resolve -- href is a typed prop passed from caller -->
<a
  class="hover:text-primary focus-visible:ring-ring relative flex gap-4 px-[1.45rem] py-2.5 transition-colors focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset {isActive
    ? 'bg-hover-dimmer hover:bg-hover-default font-medium'
    : 'hover:bg-hover-dimmer text-secondary'}"
  aria-current={isActive ? "page" : undefined}
  {href}
>
  {#if isActive}
    <div class="bg-dynamic-default absolute top-0 bottom-0 left-0 w-[4px] rounded-r-full"></div>
  {/if}
  <svelte:component this={icon} class="size-6" />
  <span>{label}</span>
  <slot />
</a>
<!-- eslint-enable svelte/no-navigation-without-resolve -->
