<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page } from "$lib/components/layout/index.js";
  import RoleEditor from "./RoleEditor.svelte";
  import RolesTable from "./RolesTable.svelte";
  import { m } from "$lib/paraglide/messages";
  import { getAppContext } from "$lib/core/AppContext";

  export let data;

  const { tenant } = getAppContext();
  const defaultRoleId = tenant.default_role_id ?? null;
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.roles()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.roles()}></Page.Title>
    <RoleEditor mode="create" permissions={data.permissions} templates={data.templates}
    ></RoleEditor>
  </Page.Header>

  <Page.Main>
    <RolesTable roles={data.allRoles} permissions={data.permissions} {defaultRoleId} />
  </Page.Main>
</Page.Root>
