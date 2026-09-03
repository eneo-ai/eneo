<!--
    Capability providers: one tab per capability (web search, image
    generation). Each tab manages the tenant's saved providers for that
    capability and which one is active. Providers are ordinary MCP servers
    under the hood, distinguished by their purpose.
-->

<script lang="ts">
  import { Page } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import { setSecurityContext } from "$lib/features/security-classifications/SecurityContext.js";
  import { CAPABILITIES } from "$lib/features/mcp/capabilities";
  import CapabilityProviderPanel from "./CapabilityProviderPanel.svelte";
  import { untrack } from "svelte";
  import type { components } from "@eneo/eneo-js";

  type MCPServerSettings = components["schemas"]["MCPServerSettingsPublic"];

  const { data } = $props();

  setSecurityContext(untrack(() => data.securityClassifications));

  const servers = $derived((data.capabilitySettings?.items ?? []) as MCPServerSettings[]);
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.capabilities()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.capabilities()}></Page.Title>
    <Page.Tabbar>
      {#each CAPABILITIES as capability (capability.purpose)}
        <Page.TabTrigger tab={capability.purpose}>{capability.label()}</Page.TabTrigger>
      {/each}
    </Page.Tabbar>
  </Page.Header>
  <Page.Main>
    {#each CAPABILITIES as capability (capability.purpose)}
      <Page.Tab id={capability.purpose}>
        <CapabilityProviderPanel
          {capability}
          providers={servers.filter((server) => server.purpose === capability.purpose)}
        />
      </Page.Tab>
    {/each}
  </Page.Main>
</Page.Root>
