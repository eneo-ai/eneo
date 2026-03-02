<script lang="ts">
  import { Table } from "@intric/ui";
  import { createRender } from "svelte-headless-table";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import type { FlowSparse } from "@intric/intric-js";
  import { IconWorkflow } from "@intric/icons/workflow";
  import PublishingStatusChip from "$lib/features/publishing/components/PublishingStatusChip.svelte";
  import FlowActions from "./FlowActions.svelte";
  import { m } from "$lib/paraglide/messages";

  export let flows: FlowSparse[];
  const table = Table.createWithResource(flows);

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
          link: `/spaces/${$currentSpace.routeId}/flows/${item.value.id}`,
          icon: IconWorkflow
        });
      }
    }),

    table.column({
      header: m.flow_steps(),
      accessor: (item) => item,
      cell: (item) => {
        const flow = item.value as FlowSparse;
        return flow.published_version != null
          ? `v${flow.published_version}`
          : m.flow_version_draft();
      }
    }),

    table.column({
      header: m.flow_last_updated(),
      accessor: (item) => item,
      cell: (item) => {
        const flow = item.value as FlowSparse;
        return flow.updated_at
          ? new Date(flow.updated_at).toLocaleDateString()
          : "-";
      }
    }),

    table.columnActions({
      cell: (item) => {
        return createRender(FlowActions, {
          flow: item.value
        });
      }
    })
  ]);

  $: table.update(flows);
</script>

{#if flows.length === 0}
  <div class="flex flex-col items-center justify-center gap-4 py-16 text-center">
    <IconWorkflow class="text-secondary size-12" />
    <h3 class="text-lg font-semibold">{m.flow_empty_title()}</h3>
    <p class="text-secondary max-w-[40ch]">{m.flow_empty_description()}</p>
  </div>
{:else}
  <Table.Root
    {viewModel}
    resourceName={m.resource_flows()}
    emptyMessage={m.flow_empty_title()}
  >
    <Table.Group></Table.Group>
  </Table.Root>
{/if}
