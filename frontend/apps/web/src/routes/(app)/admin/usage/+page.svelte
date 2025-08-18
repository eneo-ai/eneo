<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page } from "$lib/components/layout";
  import StorageSummary from "./storage/StorageSummary.svelte";
  import TokenSummary from "./tokens/TokenSummary.svelte";
  import UserTokenSummary from "./users/UserTokenSummary.svelte";

  const { data } = $props();
</script>

<svelte:head>
  <title>Eneo.ai – Admin – Usage</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title="Usage"></Page.Title>
    <Page.Tabbar>
      <Page.TabTrigger tab="storage">Storage</Page.TabTrigger>
      <Page.TabTrigger tab="tokens">Tokens</Page.TabTrigger>
      <Page.TabTrigger tab="users">Users</Page.TabTrigger>
    </Page.Tabbar>
  </Page.Header>
  <Page.Main>
    <Page.Tab id="storage">
      <StorageSummary spaces={data.spaces} storageStats={data.storageStats}></StorageSummary>
    </Page.Tab>
    <Page.Tab id="tokens">
      <TokenSummary tokenStats={data.tokenStats}></TokenSummary>
    </Page.Tab>
    <Page.Tab id="users">
      <UserTokenSummary></UserTokenSummary>
    </Page.Tab>
  </Page.Main>
</Page.Root>
