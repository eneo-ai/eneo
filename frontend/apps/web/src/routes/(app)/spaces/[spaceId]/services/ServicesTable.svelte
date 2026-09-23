<script lang="ts">
  import type { ServiceSparse } from "@eneo/eneo-js";
  import * as Table from "$lib/components/resource-table/index.js";
  import ServiceTile from "./ServiceTile.svelte";
  import ServiceActions from "./ServiceActions.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { IconService } from "@eneo/icons/service";

  export let services: ServiceSparse[];
  const table = Table.createWithResource(services);

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const viewModel = table.createViewModel([
    table.columnPrimary({
      header: "Name",
      value: (item) => item.name,
      cell: (item) => {
        return Table.renderComponent(Table.PrimaryCell, {
          label: item.value.name,
          link: `/spaces/${$currentSpace.routeId}/services/${item.value.id}`,
          icon: IconService
        });
      }
    }),

    table.columnActions({
      cell: (item) => {
        return Table.renderComponent(ServiceActions, {
          service: item.value
        });
      }
    }),

    table.columnCard({
      value: (item) => item.name,
      cell: (item) => {
        return Table.renderComponent(ServiceTile, {
          service: item.value
        });
      }
    })
  ]);

  $: table.update(services);
</script>

<Table.Root {viewModel} resourceName="service" displayAs="cards" gapX={1.5} gapY={1.5} layout="grid"
></Table.Root>
