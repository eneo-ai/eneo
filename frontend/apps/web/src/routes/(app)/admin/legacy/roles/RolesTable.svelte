<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { Permission, Role } from "@eneo/eneo-js";
  import { Label, Table } from "@eneo/ui";
  import { createRender } from "svelte-headless-table";
  import RoleActions from "./RoleActions.svelte";

  export let roles: Role[];
  export let permissions: Array<{ name: Permission; description: string }>;

  const permissionDict = permissions.reduce(
    (prev, curr) => {
      prev[curr.name] = curr.description;
      return prev;
    },
    {} as Record<Permission, string>
  );

  export let editabel = true;
  const table = Table.createWithResource(roles);

  const viewModel = table.createViewModel([
    table.column({ accessor: "name", header: "Role" }),
    table.column({
      accessor: "permissions",
      header: "Permissions",
      cell: (item) => {
        const content = item.value.map((perm) => {
          return {
            label: perm,
            tooltip: permissionDict[perm],
            color: "blue" as Label.LabelColor
          };
        });
        return createRender(Label.List, { content });
      },
      plugins: {
        sort: {
          getSortValue(item) {
            return item.length;
          }
        }
      }
    }),

    table.columnActions({
      cell: (item) => {
        return createRender(RoleActions, { permissions, role: item.value, disabled: !editabel });
      }
    })
  ]);

  $: table.update(roles);
</script>

<Table.Root {viewModel} resourceName="role"></Table.Root>
