<script lang="ts">
  import type { Role, User, Group } from "@intric/intric-js";
  import { Table, Label } from "@intric/ui";
  import UserActions from "./UserActions.svelte";
  import { createRender } from "svelte-headless-table";
  import { m } from "$lib/paraglide/messages";
  import { onMount } from "svelte";
  import { get } from "svelte/store";

  export let users: User[] = [];
  export let initialFilterValue = "";

  // Use server-side filter mode: UI renders but triggers server search
  const table = Table.createWithResource(users, 100, { serverSideFilter: true });

  // Create viewModel once (not reactive)
  const viewModel = table.createViewModel([
    table.column({ accessor: "email", header: m.email() }),
    table.column({
      accessor: (user) => user,
      header: m.roles(),  // Changed to plural
      cell: (item) => {
        // Combine predefined_roles AND custom roles
        const roles = [...(item.value.predefined_roles || []), ...(item.value.roles || [])];
        const content: { label: string; color: Label.LabelColor }[] = roles.map((role) => {
          return { label: role.name, color: "blue" };
        });
        return createRender(Label.List, { content });
      },
      plugins: {
        sort: {
          disable: true
        },
        tableFilter: {
          getFilterValue(value) {
            const roles = [...(value.predefined_roles || []), ...(value.roles || [])];
            return roles.map((role: Role) => role.name).join(" ");
          }
        }
      }
    }),
    table.column({
      accessor: (user) => user,
      header: m.user_groups(),
      cell: (item) => {
        const content: { label: string; color: Label.LabelColor }[] = (item.value.user_groups || []).map(
          (group) => {
            return { label: group.name, color: "blue" };
          }
        );
        return createRender(Label.List, { content });
      },
      plugins: {
        sort: {
          disable: true
        },
        tableFilter: {
          getFilterValue(value) {
            const groups = value.user_groups ?? [];
            return groups.map((group: Group) => group.name).join(" ");
          }
        }
      }
    }),
    table.column({
      accessor: (user) => user,
      header: m.status(),
      cell: (item) => {
        // Use state enum (not is_active boolean) to properly show all states
        // Note: 'deleted' state never appears (filtered by deleted_at IS NULL in queries)
        const stateLabels: Record<string, { label: string; color: Label.LabelColor }> = {
          active: { label: m.active(), color: "green" },
          inactive: { label: m.inactive(), color: "gray" },  // Gray = neutral (temporary leave)
          invited: { label: m.invited(), color: "blue" }
        };
        const label = stateLabels[item.value.state] || stateLabels.active;
        return createRender(Label.Single, { item: label });
      },
      plugins: {
        sort: {
          getSortValue(value) {
            return value.state;
          }
        },
        tableFilter: {
          getFilterValue(value) {
            // Map state to localized string for filtering
            const stateMap: Record<string, string> = {
              active: m.active(),
              inactive: m.inactive(),
              invited: m.invited()
            };
            return stateMap[value.state] || value.state;
          }
        }
      }
    }),
    table.columnActions({
      header: m.actions(),  // Add "Åtgärder" header for clarity
      cell: (item) => {
        return createRender(UserActions, { user: item.value });
      }
    })
  ]);

  // Reactive update with defensive check
  $: {
    table.update(users ?? []);  // Defensive: ensure always an array
  }

  // Export filterValue so parent can watch for server-side search
  export const filterValue = viewModel.pluginStates.tableFilter.filterValue;

  onMount(() => {
    const fromUrl = initialFilterValue.trim();
    if (!fromUrl) return;

    const current = get(filterValue).trim();
    if (!current) {
      filterValue.set(fromUrl);
    }
  });
</script>

<Table.Root {viewModel} resourceName={m.user()}></Table.Root>
