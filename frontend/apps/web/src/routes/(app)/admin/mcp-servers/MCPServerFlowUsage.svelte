<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import { Spinner } from "$lib/components/ui/spinner/index.js";
  import { ChevronDown, Workflow } from "@lucide/svelte";
  import { resolve } from "$app/paths";
  import { m } from "$lib/paraglide/messages";
  import { getErrorMessage } from "$lib/core/errors/getErrorMessage";
  import { getAppContext } from "$lib/core/AppContext";
  import type { Eneo } from "@eneo/eneo-js";

  type Props = {
    mcpServerId: string;
    eneoClient: Eneo;
    /** The admin-facing name of one of the server's tools. */
    toolLabel: (toolId: string) => string;
  };

  const { mcpServerId, eneoClient, toolLabel }: Props = $props();

  // A flow gets a link only where its page opens for the admin: the page
  // needs the flows_manage permission and a space the admin belongs to. The
  // spaces only decide the links, so when they cannot be read the flows are
  // listed without any.
  const canOpenFlows = getAppContext().user.hasPermission("flows_manage");
  const usage = $derived(
    Promise.all([
      eneoClient.mcpServers.flowUsage({ mcp_server_id: mcpServerId }),
      eneoClient.spaces.list().catch(() => [])
    ]).then(([found, spaces]) => ({
      ...found,
      memberSpaceIds: new Set(spaces.map((space) => space.id))
    }))
  );
</script>

<div class="text-muted mr-4 mb-2 ml-10 text-xs" aria-live="polite">
  {#await usage}
    <p class="flex items-center gap-2 px-1">
      <Spinner class="size-3.5" role="presentation" aria-hidden="true" />
      {m.mcp_flow_usage_loading()}
    </p>
  {:then found}
    {#if found.total_count === 0}
      <p class="px-1">{m.mcp_flow_usage_none()}</p>
    {:else}
      <Collapsible.Root class="border-dimmer bg-primary/30 rounded-lg border">
        <Collapsible.Trigger
          class="hover:bg-hover-dimmer group flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left"
        >
          <Workflow class="size-3.5 shrink-0" aria-hidden="true" />
          <span class="text-default font-medium">
            {found.total_count === 1
              ? m.mcp_flow_usage_singular()
              : m.mcp_flow_usage_plural({ count: found.total_count })}
          </span>
          <ChevronDown
            class="ml-auto size-3.5 transition-transform group-data-[state=open]:rotate-180"
            aria-hidden="true"
          />
        </Collapsible.Trigger>
        <Collapsible.Content class="border-dimmer space-y-2 border-t px-3 py-2">
          <p>{m.mcp_flow_usage_hint()}</p>
          <ul class="space-y-1.5">
            {#each found.items as flow (flow.flow_id)}
              <li>
                {#if canOpenFlows && found.memberSpaceIds.has(flow.space_id)}
                  <a
                    class="text-default font-medium underline-offset-2 hover:underline"
                    href={resolve(`/spaces/${flow.space_id}/flows/${flow.flow_id}`)}
                    >{flow.flow_name}</a
                  >
                {:else}
                  <span class="text-default font-medium">{flow.flow_name}</span>
                {/if}
                <span>
                  · {m.mcp_flow_usage_flow_meta({
                    space: flow.space_name,
                    version: flow.published_version
                  })}
                </span>
                <span class="block">
                  {m.mcp_flow_usage_tools({ tools: flow.tool_ids.map(toolLabel).join(", ") })}
                </span>
              </li>
            {/each}
          </ul>
          {#if found.total_count > found.items.length}
            <p>
              {m.mcp_flow_usage_shown({ shown: found.items.length, total: found.total_count })}
            </p>
          {/if}
        </Collapsible.Content>
      </Collapsible.Root>
    {/if}
  {:catch error}
    <p class="text-negative-default px-1">
      {m.mcp_flow_usage_failed()}: {getErrorMessage(error)}
    </p>
  {/await}
</div>
