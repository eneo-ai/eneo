<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page } from "$lib/components/layout";
  import CreateSpaceDialog from "$lib/features/spaces/components/CreateSpaceDialog.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import SpacesTable from "./SpacesTable.svelte";

  const {
    state: { nonOrgSpaces }
  } = getSpacesManager();
</script>

<Page.Root>
  <Page.Header>
    <Page.Title title="Your spaces"></Page.Title>
    <CreateSpaceDialog includeTrigger={true} forwardToNewSpace={false}></CreateSpaceDialog>
  </Page.Header>

  <Page.Main>
    <SpacesTable spaces={nonOrgSpaces}></SpacesTable>
  </Page.Main>
</Page.Root>