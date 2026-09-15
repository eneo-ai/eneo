<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { Role } from "@eneo/eneo-js";
  import * as Select from "$lib/components/ui/select";
  import * as Field from "$lib/components/ui/field";
  import { m } from "$lib/paraglide/messages";

  let {
    value = $bindable(),
    roles,
    disabled = false
  }: {
    value: Role[];
    roles: Role[];
    disabled?: boolean;
  } = $props();

  const id = $props.id();
  const selectedIds = $derived(value.map((role) => role.id));
  const selectedLabel = $derived(value.map((role) => role.name).join(", "));
  const defaultRoles = $derived(roles.filter((role) => role.predefined_source));
  const customRoles = $derived(roles.filter((role) => !role.predefined_source));
</script>

{#if roles.length > 0}
  <Field.Field>
    <Field.Label for={id}>{m.roles_permissions()}</Field.Label>
    <Select.Root
      type="multiple"
      value={selectedIds}
      {disabled}
      onValueChange={(ids) => {
        value = roles.filter((role) => ids.includes(role.id));
      }}
    >
      <Select.Trigger {id} class="w-full">
        <span class="truncate">{selectedLabel || m.select_ellipsis()}</span>
      </Select.Trigger>
      <Select.Content>
        {#if defaultRoles.length > 0}
          <Select.Group>
            <Select.GroupHeading>{m.default_roles()}</Select.GroupHeading>
            {#each defaultRoles as role (role.id)}
              <Select.Item value={role.id} label={role.name} />
            {/each}
          </Select.Group>
        {/if}
        {#if customRoles.length > 0}
          <Select.Group>
            <Select.GroupHeading>{m.custom_roles()}</Select.GroupHeading>
            {#each customRoles as role (role.id)}
              <Select.Item value={role.id} label={role.name} />
            {/each}
          </Select.Group>
        {/if}
      </Select.Content>
    </Select.Root>
  </Field.Field>
{/if}
