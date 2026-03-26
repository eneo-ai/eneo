<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { Permission, Role } from "@intric/intric-js";
  import { Label, Table } from "@intric/ui";
  import { createRender } from "svelte-headless-table";
  import RoleActions from "./RoleActions.svelte";
  import RoleName from "./RoleName.svelte";

  export let roles: Role[];
  export let permissions: Array<{ name: Permission; description: string }>;
  export let defaultRoleId: string | null = null;

  const permissionDict = permissions.reduce(
    (prev, curr) => {
      prev[curr.name] = curr.description;
      return prev;
    },
    {} as Record<Permission, string>
  );

  // Sort: default role first
  $: sortedRoles = [...roles].sort((a, b) => {
    if (defaultRoleId && a.id === defaultRoleId) return -1;
    if (defaultRoleId && b.id === defaultRoleId) return 1;
    return 0;
  });

  const table = Table.createWithResource(sortedRoles);

  const viewModel = table.createViewModel([
    table.column({
      accessor: (role) => role,
      header: "Role",
      cell: (item) => {
        const role = item.value;
        const isDefault = defaultRoleId != null && role.id === defaultRoleId;
        const templateSource =
          "predefined_source" in role && role.predefined_source ? role.predefined_source : null;
        return createRender(RoleName, { name: role.name, isDefault, templateSource });
      },
      plugins: {
        sort: {
          getSortValue(item) {
            return item.name;
          }
        }
      }
    }),
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
        const isDefault = defaultRoleId != null && item.value.id === defaultRoleId;
        return createRender(RoleActions, { permissions, role: item.value, isDefault });
      }
    })
  ]);

  $: table.update(sortedRoles);
</script>

<Table.Root {viewModel} resourceName="role"></Table.Root>
