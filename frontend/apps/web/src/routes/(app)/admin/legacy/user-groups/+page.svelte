<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page } from "$lib/components/layout";
  import UserGroupEditor from "./UserGroupEditor.svelte";
  import UserGroupTable from "./UserGroupTable.svelte";
  import { m } from "$lib/paraglide/messages";

  export let data;
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.user_groups()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.user_groups()}></Page.Title>
    <UserGroupEditor mode="create"></UserGroupEditor>
  </Page.Header>
  <Page.Main>
    <UserGroupTable userGroups={data.userGroups} />
  </Page.Main>
</Page.Root>
