<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { StorageSpaceList } from "@intric/intric-js";
  import { createRender } from "svelte-headless-table";
  import { Button, Table } from "@intric/ui";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import SpaceMembersChips from "$lib/features/spaces/components/SpaceMembersChips.svelte";
  import StorageSpaceName from "./StorageSpaceName.svelte";
  import { m } from "$lib/paraglide/messages";

  export let spaces: StorageSpaceList[];

  let showAllSpaces = false;

  $: visibleSpaces = showAllSpaces ? spaces : spaces.slice(0, 10);

  const table = Table.createWithResource(visibleSpaces);

  const viewModel = table.createViewModel([
    table.columnPrimary({
      header: m.name(),
      value: (item) => item.name,
      cell: (item) => {
        return createRender(StorageSpaceName, {
          space: item.value
        });
      }
    }),
    table.column({
      header: m.members(),
      accessor: "members",
      cell: (item) => {
        return createRender(SpaceMembersChips, {
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

  $: table.update(visibleSpaces);
</script>

<Table.Root {viewModel} resourceName="space" displayAs="list"></Table.Root>
{#if spaces.length > 10}
  <Button
    variant="outlined"
    class="h-12"
    on:click={() => {
      showAllSpaces = !showAllSpaces;
    }}>{showAllSpaces ? m.show_only_10_spaces() : m.show_all_spaces({ count: spaces.length })}</Button
  >
{/if}
