<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page } from "$lib/components/layout";
  import StorageSummary from "./storage/StorageSummary.svelte";
  import TokenSummary from "./tokens/TokenSummary.svelte";
  import { m } from "$lib/paraglide/messages";

  const { data } = $props();
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.usage()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.usage()}></Page.Title>
    <Page.Tabbar>
      <Page.TabTrigger tab="storage">{m.storage()}</Page.TabTrigger>
      <Page.TabTrigger tab="tokens">{m.tokens()}</Page.TabTrigger>
    </Page.Tabbar>
  </Page.Header>
  <Page.Main>
    <Page.Tab id="storage">
      <StorageSummary spaces={data.spaces} storageStats={data.storageStats}></StorageSummary>
    </Page.Tab>
    <Page.Tab id="tokens">
      <TokenSummary tokenStats={data.tokenStats}></TokenSummary>
    </Page.Tab>
  </Page.Main>
</Page.Root>
