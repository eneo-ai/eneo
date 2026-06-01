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
  import { m } from "$lib/paraglide/messages";
  import { getPermissionCopy } from "./permission-labels";

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
      header: m.role(),
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
      header: m.permissions(),
      cell: (item) => {
        const content = item.value.map((perm) => {
          const copy = getPermissionCopy(perm, permissionDict[perm] ?? "");
          return {
            label: copy.label,
            tooltip: copy.description,
            color: "blue" as Label.LabelColor
          };
        });
        // capitalize={false} preserves Swedish casing like "Delade ytor";
        // the default would force each word to title-case ("Delade Ytor").
        return createRender(Label.List, { content, capitalize: false });
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

<Table.Root {viewModel} resourceName={m.resource_roles()}></Table.Root>
