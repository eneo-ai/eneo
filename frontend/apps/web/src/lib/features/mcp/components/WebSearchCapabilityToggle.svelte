<!--
    Web search as an assistant capability. The provider is configured globally
    by the admin and resolved at ask time, so this is a pure on/off switch
    with no provider identity. Under the hood it attaches/detaches the
    purpose=web_search MCP server offered through the space:
    - Checked when the assistant has ANY web-search server attached.
    - Turning ON attaches the offered active provider.
    - Turning OFF detaches EVERY attached web-search server and its tool
      overrides, so the assistant self-heals after provider switches.
-->

<script lang="ts">
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { Input } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";
  import { Globe } from "lucide-svelte";

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
    /** The assistant's attached MCP servers (bound to the edit draft). */
    selectedMCPServers: { [key: string]: unknown }[] | undefined;
    /** MCP tool overrides sent alongside the servers. */
    selectedMCPTools?: Array<{ tool_id: string; is_enabled: boolean }>;
    /** Optional policy-filtered server list for personal assistant governance. */
    allowedMCPServers?: { [key: string]: unknown }[] | undefined;
  };

  let {
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
    const provider = spaceServers.find((server) => server.purpose === "web_search");
    if (!provider) return undefined;
    return {
      ...provider,
      tools: provider.tools?.filter((tool) => tool.is_enabled) || []
    };
  });

  let selectedWebSearchServers = $derived(
    servers.filter((server) => server.purpose === "web_search")
  );
  let webSearchOn = $derived(selectedWebSearchServers.length > 0);
  let noProvider = $derived(!offeredProvider && !webSearchOn);

  function toggleWebSearch() {
    if (webSearchOn) {
      const ids = new Set(selectedWebSearchServers.map((server) => server.id));
      const toolIds = new Set(
        selectedWebSearchServers.flatMap((server) => server.tools?.map((tool) => tool.id) ?? [])
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
  class="divide-dimmer border-default divide-y overflow-hidden rounded-xl border"
  class:pointer-events-none={noProvider}
  class:opacity-60={noProvider}
>
  <div class="transition-colors {webSearchOn ? 'bg-accent-dimmer/20' : ''}">
    <div class="flex items-center">
      <div class="flex w-10 shrink-0 items-center justify-center">
        <Globe class="text-muted h-4 w-4" aria-hidden="true" />
      </div>
      <div class="flex-1 py-2.5 pr-4">
        <Input.Switch
          value={webSearchOn}
          sideEffect={() => {
            if (!noProvider) {
              toggleWebSearch();
            }
          }}
        >
          <div class="flex flex-col gap-0.5">
            <span class="text-default font-medium">{m.web_search()}</span>
            <p class="text-muted text-xs leading-snug">
              {noProvider ? m.web_search_not_available_here_hint() : m.web_search_capability_hint()}
            </p>
          </div>
        </Input.Switch>
      </div>
    </div>
  </div>
</div>
