<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Table } from "@intric/ui";
  import UserActions from "./UserGroupActions.svelte";
  import { createRender } from "svelte-headless-table";
  import type { UserGroup } from "@intric/intric-js";
  import { m } from "$lib/paraglide/messages";

  export let userGroups: UserGroup[];

  const table = Table.createWithResource(userGroups);

  const viewModel = table.createViewModel([
    table.column({ accessor: "name", header: m.name() }),
    table.columnActions({
      cell: (item) => {
        return createRender(UserActions, { userGroup: item.value });
      }
    })
  ]);

  $: table.update(userGroups);
</script>

<Table.Root {viewModel} resourceName="user group" noItemsMessage={m.no_user_groups_configured()}></Table.Root>
