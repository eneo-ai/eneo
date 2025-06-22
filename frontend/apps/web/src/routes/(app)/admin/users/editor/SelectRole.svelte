<script lang="ts">
  import type { Role } from "@intric/intric-js";
  import { Select } from "@intric/ui";
  import { writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";

  // Array of all currently selected roles
  export let value: Role;

  // Array of all available roles
  export let availableRoles: Role[];

  const roleSelectStore = writable({
    label: availableRoles.find((role) => role.id === value.id)?.name ?? m.role_not_available(),
    value
  });

  $: value = $roleSelectStore.value;
</script>

<Select.Root
  customStore={roleSelectStore}
  class="border-default hover:bg-hover-dimmer border-b px-4 py-4"
>
  <Select.Label>{m.roles_permissions()}</Select.Label>
  <Select.Trigger placeholder={m.select_ellipsis()}></Select.Trigger>
  <Select.Options>
    {#each availableRoles as role (role.id)}
      <Select.Item value={role} label={role.name}>
        <div class="flex w-full items-center justify-between py-1">
          <span>
            {role.name}
          </span>
        </div>
      </Select.Item>
    {/each}
  </Select.Options>
</Select.Root>
