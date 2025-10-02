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

  const {
    state: { accessibleSpaces }
  } = getSpacesManager();
</script>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.your_spaces()}></Page.Title>
    <CreateSpaceDialog includeTrigger={true} forwardToNewSpace={false}></CreateSpaceDialog>
  </Page.Header>

  <Page.Main>
    <SpacesTable spaces={accessibleSpaces}></SpacesTable>
  </Page.Main>
</Page.Root>
