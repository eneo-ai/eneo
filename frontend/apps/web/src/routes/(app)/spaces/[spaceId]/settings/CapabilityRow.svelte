<!--
    One capability (web search, image generation) as a space toggle. The
    providers are configured globally by the admin and the one serving each
    user is resolved at ask time, so this is a pure on/off switch with no
    provider identity. Under the hood it attaches/detaches an active MCP
    server with this capability's purpose as a marker:
    - Checked when the space contains ANY server with this purpose, including
      a stale previously-active provider (the backend substitutes the
      user's provider at ask time).
    - Turning ON attaches an active provider that meets the space's
      security classification; when none does, the toggle is locked and
      explains why (the backend also refuses such a marker, and never calls
      a provider below the space's classification).
    - Turning OFF detaches EVERY server with this purpose so the space
      self-heals after provider switches.
-->

<script lang="ts">
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { Input, Tooltip } from "@eneo/ui";
  import { derived } from "svelte/store";
  import { qualifyingProviders, type CapabilityDescriptor } from "$lib/features/mcp/capabilities";
  import type { components } from "@eneo/eneo-js";

  type MCPTool = components["schemas"]["MCPServerToolPublic"];

  interface SelectableMCPServer {
    id: string;
    name: string;
    purpose?: string | null;
    security_classification?: { security_level: number; name?: string } | null;
    tools: MCPTool[];
  }

  interface SpaceMCPServer {
    id: string;
    name: string;
    purpose?: string | null;
    tools?: Array<{ id: string; is_enabled: boolean }>;
  }

  type Props = {
    capability: CapabilityDescriptor;
    /** The tenant-enabled servers offered to this space (all purposes). */
    selectableServers: SelectableMCPServer[];
  };

  const { capability, selectableServers }: Props = $props();

  const {
    state: { currentSpace },
    updateSpace
  } = getSpacesManager();

  // The offered list contains every ACTIVE provider for the purpose (the
  // loader filters on is_org_enabled, which mirrors activation): the tenant
  // default and any group-targeted providers. Any of them works as the
  // attached marker.
  const activeProviders = $derived(
    selectableServers.filter((server) => server.purpose === capability.purpose)
  );
  const activeProvider = $derived(
    qualifyingProviders(
      selectableServers,
      capability.purpose,
      $currentSpace.security_classification
    )[0]
  );

  // Server ids with this purpose currently attached to the space. Read from
  // the SPACE's own list (not the offered list) so the toggle stays ON even
  // when the attached id is a previously-active provider.
  const attachedCapabilityIds = derived(currentSpace, ($currentSpace) =>
    (($currentSpace.mcp_servers ?? []) as unknown as SpaceMCPServer[])
      .filter((server) => server.purpose === capability.purpose)
      .map((server) => server.id)
  );

  const capabilityOn = $derived($attachedCapabilityIds.length > 0);
  const noProvider = $derived(activeProviders.length === 0 && !capabilityOn);
  // Turning OFF is always allowed; classification only gates attaching a
  // provider: at least one active provider must meet the space's level.
  const meetsClassification = $derived(capabilityOn || noProvider || !!activeProvider);

  let saving = $state(false);

  async function toggleCapability() {
    if (saving) return;
    saving = true;
    try {
      const spaceServers = ($currentSpace.mcp_servers ?? []) as unknown as SpaceMCPServer[];
      const attached = new Set($attachedCapabilityIds);

      if (attached.size > 0) {
        const newServers = spaceServers
          .filter((server) => !attached.has(server.id))
          .map((server) => ({ id: server.id }));
        await updateSpace({ mcp_servers: newServers });
      } else if (activeProvider) {
        const newServers = [
          ...spaceServers.map((server) => ({ id: server.id })),
          { id: activeProvider.id }
        ];
        // Keep existing tool settings and enable the provider's tools.
        const existingTools = spaceServers.flatMap(
          (server) => server.tools?.map((t) => ({ tool_id: t.id, is_enabled: t.is_enabled })) ?? []
        );
        const providerTools = activeProvider.tools.map((tool) => ({
          tool_id: tool.id,
          is_enabled: true
        }));
        await updateSpace({
          mcp_servers: newServers,
          mcp_tools: [...existingTools, ...providerTools]
        });
      }
    } catch (e) {
      console.error(`Failed to toggle ${capability.purpose}:`, e);
    }
    saving = false;
  }
</script>

<Tooltip text={meetsClassification ? undefined : capability.classificationHint()}>
  <div
    class="border-default border-b last:border-b-0"
    class:pointer-events-none={noProvider || !meetsClassification || saving}
    class:opacity-60={noProvider || !meetsClassification}
  >
    <div class="hover:bg-hover-dimmer flex items-center">
      <div class="flex w-10 shrink-0 items-center justify-center">
        <capability.icon class="text-muted h-4 w-4" aria-hidden="true" />
      </div>
      <div class="flex-1 py-4 pr-4">
        <Input.Switch
          value={capabilityOn}
          sideEffect={() => {
            if (!noProvider && meetsClassification) {
              toggleCapability();
            }
          }}
        >
          <div class="flex flex-col gap-1">
            <span class="font-medium">{capability.label()}</span>
            <span class="text-muted text-sm">
              {#if noProvider}
                {capability.noActiveProviderHint()}
              {:else if !meetsClassification}
                {capability.classificationHint()}
              {:else}
                {capability.spaceHint()}
              {/if}
            </span>
          </div>
        </Input.Switch>
      </div>
    </div>
  </div>
</Tooltip>
