<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import * as Table from "$lib/components/resource-table/index.js";
  import UserActions from "./UserGroupActions.svelte";
  import MemberChipStack from "$lib/features/spaces/components/MemberChipStack.svelte";
  import type { UserGroup } from "@eneo/eneo-js";
  import { m } from "$lib/paraglide/messages";

  export let userGroups: UserGroup[];

  const table = Table.createWithResource(userGroups);

  const viewModel = table.createViewModel([
    table.column({ accessor: "name", header: m.name() }),
    table.column({
      header: m.members(),
      accessor: "users",
      cell: (item) => {
        return Table.renderComponent(MemberChipStack, {
          members: item.value ?? []
        });
      },
      plugins: {
        sort: {
          getSortValue(item) {
            return item?.length ?? 0;
          }
        }
      }
    }),
    table.columnActions({
      cell: (item) => {
        return Table.renderComponent(UserActions, { userGroup: item.value });
      }
    })
  ]);

  $: table.update(userGroups);
</script>

<Table.Root {viewModel} resourceName="user group" emptyMessage={m.no_user_groups_configured()}
></Table.Root>
