<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { SpaceSparse } from "@intric/intric-js";
  import { Table } from "@intric/ui";
  import { createRender } from "svelte-headless-table";
  import SpaceTile from "./SpaceTile.svelte";
  import SpaceActions from "./SpaceActions.svelte";
  import SpaceCell from "./SpaceCell.svelte";
  import type { Readable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";

  export let spaces: Readable<SpaceSparse[]>;
  const table = Table.createWithStore(spaces);

  const viewModel = table.createViewModel([
    table.columnPrimary({
      header: m.name(),
      value: (item) => item.name,
      cell: (item) => {
        return createRender(SpaceCell, {
          space: item.value
        });
      }
    }),

    table.columnActions({
      cell: (item) => {
        return createRender(SpaceActions, {
          space: item.value
        });
      }
    }),

    table.columnCard({
      value: (item) => item.name,
      cell: (item) => {
        return createRender(SpaceTile, {
          space: item.value
        });
      }
    })
  ]);
</script>

<Table.Root 
  {viewModel} 
  resourceName="space" 
  gapX={1.5} 
  gapY={1.5} 
  layout="grid" 
  filterPlaceholder={m.filter_spaces_placeholder()}
  listText={m.list()}
  cardsText={m.cards()}
></Table.Root>
