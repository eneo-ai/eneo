<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { StorageSpaceList } from "@eneo/eneo-js";
  import * as Table from "$lib/components/resource-table/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import SpaceMembersChips from "$lib/features/spaces/components/SpaceMembersChips.svelte";
  import StorageSpaceName from "./StorageSpaceName.svelte";
  import { m } from "$lib/paraglide/messages";

  export let spaces: StorageSpaceList[];

  let showAllSpaces = false;

  const table = Table.createWithResource(spaces, 10);

  const viewModel = table.createViewModel([
    table.columnPrimary({
      header: m.name(),
      value: (item) => item.name,
      cell: (item) => {
        return Table.renderComponent(StorageSpaceName, {
          space: item.value
        });
      }
    }),
    table.column({
      header: m.members(),
      accessor: "members",
      cell: (item) => {
        return Table.renderComponent(SpaceMembersChips, {
          members: item.value
        });
      },
      plugins: {
        sort: {
          getSortValue(item) {
            return item.length;
          }
        }
      }
    }),
    table.column({
      header: m.storage(),
      accessor: "size",
      cell: (item) => formatBytes(item.value, 2)
    })
  ]);

  $: table.update(spaces);
  $: viewModel.pluginStates.page.pageSize.set(showAllSpaces ? Math.max(spaces.length, 10) : 10);
</script>

<Table.Root {viewModel} resourceName={m.resource_spaces()} displayAs="list"></Table.Root>
{#if spaces.length > 10}
  <Button
    variant="outline"
    class="h-12"
    onclick={() => {
      showAllSpaces = !showAllSpaces;
    }}
    >{showAllSpaces ? m.show_only_10_spaces() : m.show_all_spaces({ count: spaces.length })}</Button
  >
{/if}
