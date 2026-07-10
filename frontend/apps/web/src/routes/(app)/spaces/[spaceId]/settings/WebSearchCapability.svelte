<!--
    Web search as a space capability. The provider is configured globally by
    the admin and resolved at ask time, so this is a pure on/off switch with
    no provider identity. Under the hood it attaches/detaches the active
    purpose=web_search MCP server:
    - Checked when the space contains ANY web-search server, including a stale
      previously-active provider (the backend substitutes the active one at
      ask time).
    - Turning ON attaches the currently offered active provider.
    - Turning OFF detaches EVERY web-search server so the space self-heals
      after provider switches.
-->

<script lang="ts">
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { Input, Tooltip } from "@eneo/ui";
  import { derived } from "svelte/store";
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import { Globe } from "lucide-svelte";
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
    /** The tenant-enabled servers offered to this space (all purposes). */
    selectableServers: SelectableMCPServer[];
  };

  const { selectableServers }: Props = $props();

  const {
    state: { currentSpace },
    updateSpace
  } = getSpacesManager();

  // The offered list only ever contains the active provider (the loader
  // filters on is_org_enabled, which mirrors activation for web-search).
  const activeProvider = $derived(
    selectableServers.find((server) => server.purpose === "web_search")
  );

  // Web-search server ids currently attached to the space. Read from the
  // SPACE's own list (not the offered list) so the toggle stays ON even when
  // the attached id is a previously-active provider.
  const attachedWebSearchIds = derived(currentSpace, ($currentSpace) =>
    (($currentSpace.mcp_servers ?? []) as unknown as SpaceMCPServer[])
      .filter((server) => server.purpose === "web_search")
      .map((server) => server.id)
  );

  const webSearchOn = $derived($attachedWebSearchIds.length > 0);
  const noProvider = $derived(!activeProvider && !webSearchOn);
  // Turning OFF is always allowed; classification only gates attaching the
  // active provider.
  const meetsClassification = $derived.by(() => {
    if (webSearchOn || !activeProvider) return true;
    const spaceClassification = $currentSpace.security_classification;
    if (!spaceClassification) return true;
    if (!activeProvider.security_classification) return false;
    return (
      activeProvider.security_classification.security_level >= spaceClassification.security_level
    );
  });

  let saving = $state(false);

  async function toggleWebSearch() {
    if (saving) return;
    saving = true;
    try {
      const spaceServers = ($currentSpace.mcp_servers ?? []) as unknown as SpaceMCPServer[];
      const attached = new Set($attachedWebSearchIds);

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
      console.error("Failed to toggle web search:", e);
    }
    saving = false;
  }
</script>

<Settings.Row title={m.capabilities()} description={m.capabilities_row_description()}>
  <Tooltip
    text={meetsClassification ? undefined : m.mcp_server_does_not_meet_security_classification()}
  >
    <div
      class="border-default border-b last:border-b-0"
      class:pointer-events-none={noProvider || !meetsClassification || saving}
      class:opacity-60={noProvider || !meetsClassification}
    >
      <div class="hover:bg-hover-dimmer flex items-center">
        <div class="flex w-10 shrink-0 items-center justify-center">
          <Globe class="text-muted h-4 w-4" aria-hidden="true" />
        </div>
        <div class="flex-1 py-4 pr-4">
          <Input.Switch
            value={webSearchOn}
            sideEffect={() => {
              if (!noProvider && meetsClassification) {
                toggleWebSearch();
              }
            }}
          >
            <div class="flex flex-col gap-1">
              <span class="font-medium">{m.web_search()}</span>
              <span class="text-muted text-sm">
                {noProvider
                  ? m.web_search_no_active_provider_hint()
                  : m.web_search_space_group_hint()}
              </span>
            </div>
          </Input.Switch>
        </div>
      </div>
    </div>
  </Tooltip>
</Settings.Row>
