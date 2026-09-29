<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { SpaceSparse } from "@eneo/eneo-js";
  import * as Table from "$lib/components/resource-table/index.js";
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
        return Table.renderComponent(SpaceCell, {
          space: item.value
        });
      }
    }),

    table.columnActions({
      cell: (item) => {
        return Table.renderComponent(SpaceActions, {
          space: item.value
        });
      }
    }),

    table.columnCard({
      value: (item) => item.name,
      cell: (item) => {
        return Table.renderComponent(SpaceTile, {
          space: item.value
        });
      }
    })
  ]);
</script>

<Table.Root {viewModel} resourceName={m.resource_spaces()} gapX={1.5} gapY={1.5} layout="grid"
></Table.Root>
