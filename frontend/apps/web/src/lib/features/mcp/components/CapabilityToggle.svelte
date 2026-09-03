<!--
    One capability (web search, image generation) as an assistant toggle. The
    provider is configured globally by the admin and resolved at ask time, so
    this is a pure on/off switch with no provider identity. Under the hood it
    attaches/detaches the MCP server with this capability's purpose offered
    through the space:
    - Checked when the assistant has ANY server with this purpose attached.
    - Turning ON attaches the offered active provider.
    - Turning OFF detaches EVERY attached server with this purpose and its
      tool overrides, so the assistant self-heals after provider switches.
-->

<script lang="ts">
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { Input } from "@eneo/ui";
  import type { CapabilityDescriptor } from "$lib/features/mcp/capabilities";

  interface MCPTool {
    id: string;
    name: string;
    description?: string;
    is_enabled: boolean;
  }

  interface MCPServer {
    id: string;
    name: string;
    purpose?: string;
    tools?: MCPTool[];
    [key: string]: unknown;
  }

  type Props = {
    capability: CapabilityDescriptor;
    /** The assistant's attached MCP servers (bound to the edit draft). */
    selectedMCPServers: { [key: string]: unknown }[] | undefined;
    /** MCP tool overrides sent alongside the servers. */
    selectedMCPTools?: Array<{ tool_id: string; is_enabled: boolean }>;
    /** Optional policy-filtered server list for personal assistant governance. */
    allowedMCPServers?: { [key: string]: unknown }[] | undefined;
  };

  let {
    capability,
    selectedMCPServers = $bindable([]),
    selectedMCPTools = $bindable([]),
    allowedMCPServers = undefined
  }: Props = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();

  let servers = $derived((selectedMCPServers ?? []) as unknown as MCPServer[]);

  // The space (or governance policy) offers at most the active provider.
  let offeredProvider = $derived.by(() => {
    const spaceServers = (allowedMCPServers ??
      $currentSpace.mcp_servers ??
      []) as unknown as MCPServer[];
    const provider = spaceServers.find((server) => server.purpose === capability.purpose);
    if (!provider) return undefined;
    return {
      ...provider,
      tools: provider.tools?.filter((tool) => tool.is_enabled) || []
    };
  });

  let selectedCapabilityServers = $derived(
    servers.filter((server) => server.purpose === capability.purpose)
  );
  let capabilityOn = $derived(selectedCapabilityServers.length > 0);
  let noProvider = $derived(!offeredProvider && !capabilityOn);

  function toggleCapability() {
    if (capabilityOn) {
      const ids = new Set(selectedCapabilityServers.map((server) => server.id));
      const toolIds = new Set(
        selectedCapabilityServers.flatMap((server) => server.tools?.map((tool) => tool.id) ?? [])
      );
      selectedMCPServers = servers.filter((server) => !ids.has(server.id));
      selectedMCPTools = selectedMCPTools.filter((tool) => !toolIds.has(tool.tool_id));
    } else if (offeredProvider) {
      const newServer = {
        ...offeredProvider,
        tools: offeredProvider.tools?.map((tool) => ({ ...tool, is_enabled: true })) || []
      };
      selectedMCPServers = [...servers, newServer];
      const toolOverrides =
        offeredProvider.tools?.map((tool) => ({ tool_id: tool.id, is_enabled: true })) ?? [];
      selectedMCPTools = [...selectedMCPTools, ...toolOverrides];
    }
  }
</script>

<div
  class="border-default border-b transition-colors last:border-b-0 {capabilityOn
    ? 'bg-accent-dimmer/20'
    : ''}"
  class:pointer-events-none={noProvider}
  class:opacity-60={noProvider}
>
  <div class="flex items-center">
    <div class="flex w-10 shrink-0 items-center justify-center">
      <capability.icon class="text-muted h-4 w-4" aria-hidden="true" />
    </div>
    <div class="flex-1 py-2.5 pr-4">
      <Input.Switch
        value={capabilityOn}
        sideEffect={() => {
          if (!noProvider) {
            toggleCapability();
          }
        }}
      >
        <div class="flex flex-col gap-0.5">
          <span class="text-default font-medium">{capability.label()}</span>
          <p class="text-muted text-xs leading-snug">
            {noProvider ? capability.notAvailableHereHint() : capability.capabilityHint()}
          </p>
        </div>
      </Input.Switch>
    </div>
  </div>
</div>
