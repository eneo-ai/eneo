<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { Icon } from "@eneo/icons";
  import { Button } from "$lib/components/ui/button/index.js";
  import { cn } from "$lib/utils.js";

  type Props = {
    label: string;
    link?: string;
    linkIsExternal?: boolean;
    onclick?: () => void;
    icon?: Icon;
  };

  let { label, link, linkIsExternal = false, onclick, icon }: Props = $props();
</script>

<div class="flex w-full items-center justify-start">
  <Button
    href={link}
    target={linkIsExternal ? "_blank" : undefined}
    rel={linkIsExternal ? "noopener noreferrer" : undefined}
    variant="ghost"
    onclick={() => onclick?.()}
    class={cn("group max-w-full justify-start", icon ? "-ml-1" : "-ml-2")}
  >
    {#if icon}
      {@const CellIcon = icon}
      <CellIcon class="text-muted group-hover:text-primary min-w-6" />
    {/if}
    <span class="truncate">{label}</span>
    {#if linkIsExternal}
      <svg
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        stroke-width="1.7"
        class="-ml-1 w-5 min-w-5"
        aria-hidden="true"
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
