<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { Role } from "@intric/intric-js";
  import { Select } from "@intric/ui";
  import { writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";

  // Array of all currently selected roles
  export let value: Role[];

  // Array of all available roles
  export let defaultRoles: Role[];
  export let customRoles: Role[];

  const allRoles = [...customRoles, ...defaultRoles];

  function getStoreValue() {
    const selectedIds = value.map((role) => role.id);
    const selectedRoles = allRoles.filter((role) => selectedIds.includes(role.id));
    return selectedRoles.map((role) => {
      return {
        value: role,
        label: role.name
      };
    });
  }

  let roleSelectStore = writable(getStoreValue());

  function setValue(currentlySelected: { value: Role }[]) {
    value = currentlySelected.map((item) => item.value);
  }

  $: setValue($roleSelectStore);
</script>

{#if allRoles.length > 0}
  <Select.Root
    multiple
    customStore={roleSelectStore}
    class="border-default hover:bg-hover-dimmer border-b px-4 py-4"
  >
    <Select.Label>{m.roles_permissions()}</Select.Label>
    <Select.Trigger placeholder={m.select_ellipsis()}></Select.Trigger>
    <Select.Options>
      <Select.OptionGroup label={m.default_roles()}>
        {#each defaultRoles as role (role.id)}
          <Select.Item value={role} label={role.name}>
            <div class="flex w-full items-center justify-between py-1">
              <span>
                {role.name}
              </span>
            </div>
          </Select.Item>
        {/each}
      </Select.OptionGroup>
      {#if customRoles.length > 0}
        <Select.OptionGroup label={m.custom_roles()}>
          {#each customRoles as role (role.id)}
            <Select.Item value={role} label={role.name}></Select.Item>
          {/each}
        </Select.OptionGroup>
      {/if}
    </Select.Options>
  </Select.Root>
{/if}
