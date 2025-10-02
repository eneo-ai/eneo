<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page } from "$lib/components/layout/index.js";
  import RoleEditor from "./RoleEditor.svelte";
  import RolesTable from "./RolesTable.svelte";
  import { m } from "$lib/paraglide/messages";

  export let data;
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.roles()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.roles()}></Page.Title>
    <Page.Tabbar>
      <Page.TabTrigger tab="custom_roles">{m.custom_roles()}</Page.TabTrigger>
      <Page.TabTrigger tab="default_roles">{m.default_roles()}</Page.TabTrigger>
    </Page.Tabbar>
    <RoleEditor mode="create" permissions={data.permissions}></RoleEditor>
  </Page.Header>

  <Page.Main>
    <Page.Tab id="custom_roles">
      <RolesTable roles={data.customRoles} permissions={data.permissions} />
    </Page.Tab>
    <Page.Tab id="default_roles">
      {#if data.defaultRoles.length > 0}
        <RolesTable roles={data.defaultRoles} permissions={data.permissions} editabel={false} />
      {/if}
    </Page.Tab>
  </Page.Main>
</Page.Root>
