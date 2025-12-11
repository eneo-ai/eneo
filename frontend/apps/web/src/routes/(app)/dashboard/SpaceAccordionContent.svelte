<script lang="ts">
  import { createAccordion } from "@melt-ui/svelte";
  import { slide } from "svelte/transition";
  import { IconChevronRight } from "@intric/icons/chevron-right";
  import DashboardTile from "./DashboardTile.svelte";
  import DashboardAppTile from "./DashboardAppTile.svelte";
  import type { Dashboard } from "@intric/intric-js";

  type SpaceDashboard = Dashboard["spaces"]["items"][number];

  export let space: SpaceDashboard;

  const hasAssistants = space.applications.assistants.count > 0;
  const hasApps = space.applications.apps.count > 0;

  const defaultSections: string[] = [];
  if (hasAssistants) defaultSections.push(`${space.id}-assistants`);
  if (hasApps) defaultSections.push(`${space.id}-apps`);

  const {
    elements: { content, item, trigger, root },
    helpers: { isSelected }
  } = createAccordion({
    multiple: true,
    defaultValue: defaultSections
  });
</script>

<div {...$root} class="flex flex-col">
  <!-- Assistants Section -->
  {#if hasAssistants}
    <div {...$item(`${space.id}-assistants`)} use:item>
      <button
        class="hover:bg-hover-dimmer flex w-full items-center justify-between px-4 py-3 font-mono text-xs uppercase"
        {...$trigger(`${space.id}-assistants`)}
        use:trigger
      >
        <span>Assistants ({space.applications.assistants.count})</span>
        <IconChevronRight
          class={$isSelected(`${space.id}-assistants`)
            ? "rotate-90 transition-all h-4 w-4"
            : "transition-all h-4 w-4"}
        />
      </button>

      {#if $isSelected(`${space.id}-assistants`)}
        <div
          {...$content(`${space.id}-assistants`)}
          use:content
          transition:slide
          class="grid grid-cols-2 gap-4 px-4 pb-4 md:grid-cols-3 lg:grid-cols-4"
        >
          {#each space.applications.assistants.items as assistant (assistant.id)}
            <DashboardTile {assistant} />
          {/each}
        </div>
      {/if}
    </div>
  {/if}

  <!-- Apps Section -->
  {#if hasApps}
    <div {...$item(`${space.id}-apps`)} use:item>
      <button
        class="hover:bg-hover-dimmer flex w-full items-center justify-between px-4 py-3 font-mono text-xs uppercase"
        {...$trigger(`${space.id}-apps`)}
        use:trigger
      >
        <span>Apps ({space.applications.apps.count})</span>
        <IconChevronRight
          class={$isSelected(`${space.id}-apps`)
            ? "rotate-90 transition-all h-4 w-4"
            : "transition-all h-4 w-4"}
        />
      </button>

      {#if $isSelected(`${space.id}-apps`)}
        <div
          {...$content(`${space.id}-apps`)}
          use:content
          transition:slide
          class="grid grid-cols-2 gap-4 px-4 pb-4 md:grid-cols-3 lg:grid-cols-4"
        >
          {#each space.applications.apps.items as app (app.id)}
            <DashboardAppTile {app} />
          {/each}
        </div>
      {/if}
    </div>
  {/if}
</div>
