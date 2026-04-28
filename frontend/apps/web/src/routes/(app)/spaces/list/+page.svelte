<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page } from "$lib/components/layout";
  import CreateSpaceDialog from "$lib/features/spaces/components/CreateSpaceDialog.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import SpacesTable from "./SpacesTable.svelte";
  import { m } from "$lib/paraglide/messages";
  import { getAppContext } from "$lib/core/AppContext";

  const {
    state: { nonOrgSpaces }
  } = getSpacesManager();
  const { user } = getAppContext();
  const canCreateSharedSpace = user.hasPermission("shared_spaces");
</script>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.your_spaces()}></Page.Title>
    {#if canCreateSharedSpace}
      <CreateSpaceDialog includeTrigger={true} forwardToNewSpace={true}></CreateSpaceDialog>
    {/if}
  </Page.Header>

  <Page.Main>
    <SpacesTable spaces={nonOrgSpaces}></SpacesTable>
  </Page.Main>
</Page.Root>
