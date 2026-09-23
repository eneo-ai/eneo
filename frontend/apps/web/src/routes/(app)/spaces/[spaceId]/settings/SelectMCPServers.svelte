<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { isCapabilityPurpose } from "$lib/features/mcp/capabilities";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { derived } from "svelte/store";
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import { ChevronRight } from "lucide-svelte";
  import type { components } from "@eneo/eneo-js";
  import { SvelteSet } from "svelte/reactivity";

  type MCPTool = components["schemas"]["MCPServerToolPublic"];

  interface SelectableMCPServer {
    id: string;
    name: string;
    description?: string | null;
    purpose?: string | null;
    tags?: string[] | null;
    security_classification?: { security_level: number; name?: string } | null;
    tools: MCPTool[];
  }

  /** Tool as seen on a space MCP server (uses is_enabled instead of is_enabled_by_default) */
  interface SpaceMCPTool {
    id: string;
    name: string;
    description?: string | null;
    is_enabled: boolean;
  }

  function meetsSecurityClassification(
    server: { security_classification?: { security_level: number } | null },
    spaceClassification: { security_level: number } | null | undefined
  ): boolean {
    if (!spaceClassification) return true;
    if (!server.security_classification) return false;
    return server.security_classification.security_level >= spaceClassification.security_level;
  }

  type Props = {
    selectableServers: SelectableMCPServer[];
  };

  const { selectableServers }: Props = $props();
  const uid = $props.id();

  // This section manages general-purpose servers only; capabilities (web
  // search, image generation) have their own settings rows (CapabilityRow).
  const generalServers = $derived(
    selectableServers.filter((server) => !isCapabilityPurpose(server.purpose))
  );

  // Track expanded servers
  const expandedServers = new SvelteSet<string>();

  function toggleExpanded(serverId: string) {
    if (expandedServers.has(serverId)) {
      expandedServers.delete(serverId);
    } else {
      expandedServers.add(serverId);
    }
  }

  const {
    state: { currentSpace },
    updateSpace
  } = getSpacesManager();

  /** Cast untyped space MCP servers to a usable shape */
  interface SpaceMCPServer {
    id: string;
    name: string;
    purpose?: string | null;
    tools?: SpaceMCPTool[];
  }

  function getSpaceMCPServers(): SpaceMCPServer[] {
    return ($currentSpace.mcp_servers ?? []) as unknown as SpaceMCPServer[];
  }

  const currentlySelectedServers = derived(currentSpace, ($currentSpace) =>
    (($currentSpace.mcp_servers ?? []) as unknown as SpaceMCPServer[]).map((server) => server.id)
  );

  // Get tools for a specific server from current space
  function getServerTools(serverId: string): SpaceMCPTool[] {
    const servers = getSpaceMCPServers();
    const server = servers.find((s) => s.id === serverId);
    return server?.tools ?? [];
  }

  const loading = new SvelteSet<string>();

  async function toggleServer(server: SelectableMCPServer) {
    loading.add(server.id);

    try {
      if ($currentlySelectedServers.includes(server.id)) {
        const newServers = $currentlySelectedServers
          .filter((id) => id !== server.id)
          .map((id) => ({ id }));
        await updateSpace({ mcp_servers: newServers });
      } else {
        const newServers = [...$currentlySelectedServers, server.id].map((id) => ({ id }));

        // When adding a server, enable all its tools for convenience
        const spaceServers = getSpaceMCPServers();
        const existingTools = spaceServers.flatMap(
          (s) => s.tools?.map((t) => ({ tool_id: t.id, is_enabled: t.is_enabled })) ?? []
        );

        // Add all tools from the new server as enabled
        const newServerTools =
          server.tools?.map((t) => ({ tool_id: t.id, is_enabled: true })) ?? [];

        await updateSpace({
          mcp_servers: newServers,
          mcp_tools: [...existingTools, ...newServerTools]
        });
      }
    } catch (e) {
      console.error("Failed to toggle server:", e);
    }

    loading.delete(server.id);
  }

  async function toggleTool(tool: SpaceMCPTool) {
    try {
      // Get current tool settings from space
      const spaceServers = getSpaceMCPServers();
      const currentTools = spaceServers.flatMap(
        (server) => server.tools?.map((t) => ({ tool_id: t.id, is_enabled: t.is_enabled })) ?? []
      );

      // Toggle this tool
      const toolExists = currentTools.find((t) => t.tool_id === tool.id);
      const newTools = toolExists
        ? currentTools.map((t) =>
            t.tool_id === tool.id ? { tool_id: t.tool_id, is_enabled: !t.is_enabled } : t
          )
        : [...currentTools, { tool_id: tool.id, is_enabled: !tool.is_enabled }];

      await updateSpace({ mcp_tools: newTools });
    } catch (e) {
      console.error("Failed to toggle tool:", e);
    }
  }
</script>

<Settings.Row title={m.tools()} description={m.mcp_settings_row_description()}>
  <svelte:fragment slot="description">
    {#if ($currentSpace.mcp_servers?.length ?? 0) === 0}
      <p
        class="label-warning border-label-default bg-label-dimmer text-label-stronger mt-2.5 rounded-md border px-2 py-1 text-sm"
      >
        <span class="font-bold">{m.hint()}:&nbsp;</span>{m.mcp_enable_server_hint()}
      </p>
    {/if}
  </svelte:fragment>

  <div class:border={generalServers.length > 0} class="border-default overflow-hidden rounded-xl">
    {#each generalServers as server (server.id)}
      {@const serverTools = getServerTools(server.id)}
      {@const hasTools = $currentlySelectedServers.includes(server.id) && serverTools.length > 0}
      {@const isExpanded = expandedServers.has(server.id)}
      {@const meetsClassification = meetsSecurityClassification(
        server,
        $currentSpace.security_classification
      )}
      {#snippet serverBlock()}
        <div
          class="border-default border-b last:border-b-0"
          class:pointer-events-none={!meetsClassification}
          class:opacity-60={!meetsClassification}
        >
          <!-- Server Row -->
          <div
            class="hover:bg-hover-dimmer flex items-center {$currentlySelectedServers.includes(
              server.id
            )
              ? 'bg-accent-dimmer/20'
              : ''}"
          >
            <!-- Expand Button -->
            <button
              type="button"
              class="flex h-full w-10 shrink-0 items-center justify-center p-2 disabled:opacity-30"
              disabled={!hasTools}
              onclick={() => toggleExpanded(server.id)}
              aria-label={isExpanded
                ? m.governance_mcp_hide_tools()
                : m.governance_mcp_show_tools()}
              aria-expanded={isExpanded}
            >
              <ChevronRight class="h-4 w-4 transition-transform {isExpanded ? 'rotate-90' : ''}" />
            </button>

            <!-- Server Toggle -->
            <div class="min-w-0 flex-1 py-2.5 pr-4">
              <Field.Field orientation="horizontal">
                <Field.Content class="gap-1">
                  <Field.Label for={`${uid}-server-${server.id}`}>
                    <span class="font-medium">{server.name}</span>
                    {#if hasTools}
                      <span class="text-muted text-xs font-normal"
                        >({serverTools.length} {m.tools()})</span
                      >
                    {/if}
                  </Field.Label>
                  {#if server.description}
                    <Field.Description
                      id={`${uid}-server-${server.id}-description`}
                      class="text-muted text-sm">{server.description}</Field.Description
                    >
                  {/if}
                  {#if server.tags && server.tags.length > 0}
                    <div class="text-muted flex gap-2 text-xs">
                      {#each server.tags as tag (tag)}
                        <span
                          class="inline-flex items-center rounded-full border border-gray-300 px-2 py-0.5 text-xs font-medium text-gray-700 dark:border-gray-600 dark:text-gray-300"
                          >{tag}</span
                        >
                      {/each}
                    </div>
                  {/if}
                </Field.Content>
                <Switch
                  id={`${uid}-server-${server.id}`}
                  checked={$currentlySelectedServers.includes(server.id)}
                  onCheckedChange={() => {
                    if (meetsClassification) {
                      toggleServer(server);
                    }
                  }}
                  aria-describedby={server.description
                    ? `${uid}-server-${server.id}-description`
                    : undefined}
                />
              </Field.Field>
            </div>
          </div>

          <!-- Tools List (only show if expanded) -->
          {#if hasTools && isExpanded}
            <div class="pr-4 pb-2 pl-10">
              <div class="text-muted mb-2 text-xs font-medium">{m.tools()}</div>
              {#each serverTools as tool (tool.id)}
                <div class="border-dimmer hover:bg-hover-dimmer border-b py-2 last:border-b-0">
                  <Field.Field orientation="horizontal">
                    <Field.Content>
                      <Field.Label for={`${uid}-tool-${tool.id}`}>{tool.name}</Field.Label>
                      {#if tool.description}
                        <Field.Description
                          id={`${uid}-tool-${tool.id}-description`}
                          class="text-muted line-clamp-2 text-xs"
                          >{tool.description}</Field.Description
                        >
                      {/if}
                    </Field.Content>
                    <Switch
                      id={`${uid}-tool-${tool.id}`}
                      checked={tool.is_enabled}
                      onCheckedChange={() => toggleTool(tool)}
                      aria-describedby={tool.description
                        ? `${uid}-tool-${tool.id}-description`
                        : undefined}
                    />
                  </Field.Field>
                </div>
              {/each}
            </div>
          {/if}
        </div>
      {/snippet}
      {#if meetsClassification}
        {@render serverBlock()}
      {:else}
        <Tooltip.Root>
          <Tooltip.Trigger tabindex={-1}>
            {#snippet child({ props })}
              <div {...props}>{@render serverBlock()}</div>
            {/snippet}
          </Tooltip.Trigger>
          <Tooltip.Content>{m.mcp_server_does_not_meet_security_classification()}</Tooltip.Content>
        </Tooltip.Root>
      {/if}
    {/each}
  </div>
</Settings.Row>
