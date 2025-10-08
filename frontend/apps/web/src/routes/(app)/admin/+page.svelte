<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page, Settings } from "$lib/components/layout/index.js";
  import { getAppContext } from "$lib/core/AppContext.js";
  import StorageOverviewBar from "./usage/storage/StorageOverviewBar.svelte";
  import TokenOverviewBar from "./usage/tokens/TokenOverviewBar.svelte";
  import { m } from "$lib/paraglide/messages";

  const { tenant } = getAppContext();
  export let data;
</script>

<svelte:head>
  <title>Eneo.ai - {tenant.display_name}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.organisation()}></Page.Title>
  </Page.Header>
  <Page.Main>
    <Settings.Page>
      <Settings.Group title={m.usage()}>
        <StorageOverviewBar storageStats={data.storageStats}></StorageOverviewBar>
        <TokenOverviewBar tokenStats={data.tokenStats}></TokenOverviewBar>
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>
