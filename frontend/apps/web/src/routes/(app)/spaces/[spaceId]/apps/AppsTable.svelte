<script lang="ts">
  import { Table } from "@intric/ui";
  import { createRender } from "svelte-headless-table";
  import AppTile from "./AppTile.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import type { AppSparse } from "@intric/intric-js";
  import { IconApp } from "@intric/icons/app";
  import PublishingStatusChip from "$lib/features/publishing/components/PublishingStatusChip.svelte";
  import AppActions from "./AppActions.svelte";
  import { m } from "$lib/paraglide/messages";

  export let apps: AppSparse[];
  const table = Table.createWithResource(apps);

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const viewModel = table.createViewModel([
    table.columnPrimary({
      header: m.name(),
      value: (item) => item.name,
      cell: (item) => {
        return createRender(Table.PrimaryCell, {
          label: item.value.name,
          link: `/spaces/${$currentSpace.routeId}/apps/${item.value.id}`,
          icon: IconApp
        });
      }
    }),

    // Only show status if we're not in the personal space
    ...(!$currentSpace.personal
      ? [
          table.column({
            header: m.status(),
            accessor: (item) => item,
            cell: (item) => {
              return createRender(PublishingStatusChip, {
                resource: item.value
              });
            }
          })
        ]
      : []),

    table.columnActions({
      cell: (item) => {
        return createRender(AppActions, {
          app: item.value
        });
      }
    }),

    table.columnCard({
      value: (item) => item.name,
      cell: (item) => {
        return createRender(AppTile, {
          app: item.value
        });
      }
    })
  ]);

  $: table.update(apps);

  function isPublished(status: boolean): (assistant: { published: boolean }) => boolean {
    return (assistant: { published: boolean }) => assistant.published === status;
  }
</script>

<Table.Root 
  {viewModel} 
  resourceName="app" 
  displayAs="cards" 
  gapX={1.5} 
  gapY={1.5} 
  layout="grid"
  emptyMessage={m.there_are_currently_no_apps_configured()}
>
  {#if $currentSpace.hasPermission("publish", "app")}
    <Table.Group title={m.published()} filterFn={isPublished(true)}></Table.Group>
    <Table.Group title={m.drafts()} filterFn={isPublished(false)}></Table.Group>
  {:else}
    <Table.Group></Table.Group>
  {/if}
</Table.Root>
