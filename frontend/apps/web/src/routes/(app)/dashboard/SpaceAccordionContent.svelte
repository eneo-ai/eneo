<script lang="ts">
  import * as Accordion from "$lib/components/ui/accordion/index.js";
  import { Accordion as AccordionPrimitive } from "bits-ui";
  import DashboardTile from "./DashboardTile.svelte";
  import DashboardAppTile from "./DashboardAppTile.svelte";
  import type { Dashboard } from "@eneo/eneo-js";
  import { m } from "$lib/paraglide/messages";

  type SpaceDashboard = Dashboard["spaces"]["items"][number];

  export let space: SpaceDashboard;

  // Combine regular assistants with default_assistant (only for personal spaces)
  const allAssistants = [
    ...(space.personal && space.default_assistant ? [space.default_assistant] : []),
    ...(space.applications?.assistants.items ?? [])
  ];
  const hasAssistants = allAssistants.length > 0;
  const hasApps = (space.applications?.apps.count ?? 0) > 0;

  const defaultSections: string[] = [];
  if (hasAssistants) defaultSections.push(`${space.id}-assistants`);
  if (hasApps) defaultSections.push(`${space.id}-apps`);

  let openSections = defaultSections;
</script>

<Accordion.Root type="multiple" bind:value={openSections}>
  {#if hasAssistants}
    <Accordion.Item value={`${space.id}-assistants`}>
      <Accordion.Trigger
        level={3}
        class="hover:bg-hover-dimmer items-center rounded-none px-4 py-3 font-mono text-xs uppercase hover:no-underline"
      >
        {m.dashboard_assistants_count({ count: allAssistants.length })}
      </Accordion.Trigger>
      <AccordionPrimitive.Content
        class="grid grid-cols-2 gap-4 px-4 pb-4 md:grid-cols-3 lg:grid-cols-4"
      >
        {#each allAssistants as assistant (assistant.id)}
          <DashboardTile {assistant} />
        {/each}
      </AccordionPrimitive.Content>
    </Accordion.Item>
  {/if}

  {#if hasApps}
    <Accordion.Item value={`${space.id}-apps`}>
      <Accordion.Trigger
        level={3}
        class="hover:bg-hover-dimmer items-center rounded-none px-4 py-3 font-mono text-xs uppercase hover:no-underline"
      >
        {m.dashboard_apps_count({ count: space.applications?.apps.count ?? 0 })}
      </Accordion.Trigger>
      <AccordionPrimitive.Content
        class="grid grid-cols-2 gap-4 px-4 pb-4 md:grid-cols-3 lg:grid-cols-4"
      >
        {#each space.applications?.apps.items ?? [] as app (app.id)}
          <DashboardAppTile {app} />
        {/each}
      </AccordionPrimitive.Content>
    </Accordion.Item>
  {/if}
</Accordion.Root>
