<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconAssistant } from "@intric/icons/assistant";
  import { Table } from "@intric/ui";
  import { createRender } from "svelte-headless-table";
  import { m } from "$lib/paraglide/messages";

  type AssistantRow = {
    id: string;
    name: string;
    space_id: string;
    space_name: string;
    space_short_id: string;
    has_space_name: boolean;
    logging_enabled: boolean;
  };

  export let assistants: AssistantRow[];
  const table = Table.createWithResource(assistants);

  const viewModel = table.createViewModel([
    table.columnPrimary({
      header: "Name",
      value: (item) => `${item.name} ${item.space_name}`,
      cell: (item) => {
        const row = item.value;
        const visibleSpace = row.has_space_name
          ? row.space_name
          : `${row.space_name} (${row.space_short_id})`;
        return createRender(Table.PrimaryCell, {
          label: `${row.name} (Space: ${visibleSpace})`,
          tooltip: `Space-ID: ${row.space_id}`,
          link: `/admin/insights/assistant/${row.id}`,
          icon: IconAssistant
        });
      }
    }),
    table.column({
      header: m.logging(),
      accessor: "logging_enabled",
      cell: (item) => (item.value ? m.enabled() : "–"),
      plugins: {
        sort: { getSortValue: (item) => item.logging_enabled ?? 0 }
      }
    })
  ]);

  $: table.update(assistants);
</script>

<Table.Root {viewModel} resourceName="assistant"></Table.Root>
