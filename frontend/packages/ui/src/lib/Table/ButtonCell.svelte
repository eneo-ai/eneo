<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import Button from "$lib/Button/Button.svelte";
  import type { ComponentType, SvelteComponent } from "svelte";

  export let label: string;
  export let link: string | undefined = undefined;
  export let linkIsExternal = false;
  export let onclick: (() => void) | undefined = undefined;
  export let icon:
    | ComponentType<SvelteComponent<{ size?: "small" | "base" | "large"; class?: string }>>
    | undefined = undefined;
</script>

<div class="flex w-full items-center justify-start">
  <Button
    href={link}
    target={linkIsExternal ? "_blank" : undefined}
    on:click={() => {
      if (onclick) {
        onclick();
      }
    }}
    padding={icon ? "icon-leading" : undefined}
    class="{icon ? '-ml-1' : '-ml-2'} max-w-full"
  >
    {#if icon}
      <svelte:component this={icon} size="base" class="text-muted group-hover:text-primary min-w-6"
      ></svelte:component>
    {/if}
    <span class="truncate overflow-ellipsis">
      {label}
    </span>
    {#if linkIsExternal}
      <svg
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        stroke-width="1.7"
        class="-ml-1 w-5 min-w-5"
      >
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25"
        />
      </svg>
    {/if}
  </Button>
</div>
