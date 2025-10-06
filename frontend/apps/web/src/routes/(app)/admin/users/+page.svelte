<script lang="ts">
  import { Page } from "$lib/components/layout";
  import { setAdminUserCtx } from "./ctx";
  import InviteUser from "./editor/InviteUser.svelte";
  import UserTable from "./UserTable.svelte";
  import { m } from "$lib/paraglide/messages";

  export let data;

  setAdminUserCtx({
    customRoles: data.customRoles,
    defaultRoles: data.defaultRoles,
    userGroups: data.userGroups
  });
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.users()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.users()}></Page.Title>
    <InviteUser></InviteUser>
  </Page.Header>
  <Page.Main>
    <UserTable users={data.users} />
  </Page.Main>
</Page.Root>
