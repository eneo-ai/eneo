<script lang="ts">
  import * as Breadcrumb from "$lib/components/ui/breadcrumb/index.js";
  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import type { Snippet } from "svelte";

  let {
    flowName,
    backHref,
    activeTab = $bindable("builder"),
    tabs,
    onTabChange,
    actions
  }: {
    flowName: string;
    backHref: string;
    activeTab?: string;
    tabs: Array<{ value: string; label: string; visible?: boolean }>;
    onTabChange?: (value: string) => void;
    actions?: Snippet;
  } = $props();
</script>

<header class="border-default bg-primary sticky top-0 z-[60] ml-6 border-b">
  <!-- Row 1: Back + Title + Actions -->
  <div class="flex items-center gap-3 px-4 py-2.5 sm:px-5">
    <!-- Back arrow + flow name -->
    <div class="flex min-w-0 flex-1 items-center gap-2">
      <a
        href={backHref}
        class="text-muted hover:text-primary hover:bg-hover-dimmer -ml-1 inline-flex size-8 shrink-0 items-center justify-center rounded-lg transition-colors"
        aria-label="Tillbaka till flöden"
      >
        <svg
          class="size-4"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M10 3L5 8l5 5" />
        </svg>
      </a>
      <h1 class="truncate text-lg leading-tight font-bold tracking-[-0.01em]">
        {flowName}
      </h1>
    </div>

    <!-- Actions: badges + buttons -->
    {#if actions}
      <div class="flex shrink-0 items-center gap-2">
        {@render actions()}
      </div>
    {/if}
  </div>

  <!-- Row 2: Tabs — centered -->
  <div class="flex justify-center px-4 sm:px-5">
    <Tabs.Root bind:value={activeTab} onValueChange={(v) => onTabChange?.(v)}>
      <Tabs.List variant="line" class="h-10">
        {#each tabs as tab (tab.value)}
          {#if tab.visible !== false}
            <Tabs.Trigger value={tab.value} class="text-sm">{tab.label}</Tabs.Trigger>
          {/if}
        {/each}
      </Tabs.List>
    </Tabs.Root>
  </div>
</header>
