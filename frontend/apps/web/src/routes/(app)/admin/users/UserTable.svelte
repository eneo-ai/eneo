<script lang="ts">
  import type { Role, User } from "@intric/intric-js";
  import { Table, Label } from "@intric/ui";
  import UserActions from "./UserActions.svelte";
  import { createRender } from "svelte-headless-table";
  import { m } from "$lib/paraglide/messages";

  export let users: User[];
  const table = Table.createWithResource(users);

  const viewModel = table.createViewModel([
    table.column({ accessor: "email", header: m.email() }),
    table.column({
      accessor: (user) => user,
      header: m.role(),
      cell: (item) => {
        const content: { label: string; color: Label.LabelColor }[] =
          item.value.predefined_roles.map((group) => {
            return { label: group.name, color: "blue" };
          });
        return createRender(Label.List, { content });
      },
      plugins: {
        sort: {
          disable: true
        },
        tableFilter: {
          getFilterValue(value) {
            return value.predefined_roles.map((role: Role) => role.name).join(" ");
          }
        }
      }
    }),
    table.column({
      accessor: (user) => user,
      header: m.active(),
      cell: (item) => {
        const label: { label: string; color: Label.LabelColor } = item.value.is_active
          ? {
              label: m.active(),
              color: "green"
            }
          : { label: m.invited(), color: "gray" };
        return createRender(Label.Single, { item: label });
      },
      plugins: {
        sort: {
          getSortValue(value) {
            return value.is_active;
          }
        },
        tableFilter: {
          getFilterValue(value) {
            return value.is_active ? m.active() : m.invited();
          }
        }
      }
    }),
    table.columnActions({
      cell: (item) => {
        return createRender(UserActions, { user: item.value });
      }
    })
  ]);

  $: table.update(users);
</script>

<Table.Root {viewModel} resourceName={m.user()}></Table.Root>
