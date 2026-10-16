<script lang="ts">
  import Plug from "@lucide/svelte/icons/plug";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import { formatList } from "$lib/core/formatting/formatList";
  import { m } from "$lib/paraglide/messages";
  import type { AIBuilderSessionTool } from "./protocol";

  interface Props {
    /** The space's MCP tools, usable or not. */
    tools: AIBuilderSessionTool[];
  }

  let { tools }: Props = $props();

  // Only a tool a flow may call now is worth mentioning in a request.
  const usable = $derived(tools.filter((tool) => tool.refusal === null));
  const servers = $derived(formatList([...new Set(usable.map((tool) => tool.mcp_server_name))]));
  const label = $derived(
    usable.length === 1
      ? m.ai_builder_tools_chip_one({ servers })
      : m.ai_builder_tools_chip({ servers, count: String(usable.length) })
  );
</script>

{#if usable.length > 0}
  <Popover.Root>
    <Popover.Trigger>
      {#snippet child({ props })}
        <Button
          {...props}
          variant="outline"
          size="xs"
          class="text-secondary h-auto max-w-full rounded-full border-dashed py-1 font-normal whitespace-normal"
        >
          <Plug data-icon="inline-start" aria-hidden="true" />
          <span class="text-left">{label}</span>
        </Button>
      {/snippet}
    </Popover.Trigger>
    <Popover.Content align="start" class="w-80">
      <Popover.Header>
        <Popover.Title>{m.ai_builder_tools_popover_title()}</Popover.Title>
        <Popover.Description>{m.ai_builder_tools_popover_hint()}</Popover.Description>
      </Popover.Header>
      <ul class="flex max-h-[min(20rem,50vh)] list-none flex-col gap-2.5 overflow-y-auto p-0">
        {#each usable as tool (tool.ref)}
          <li class="flex min-w-0 flex-col gap-0.5">
            <span class="flex min-w-0 flex-wrap items-baseline gap-x-1.5">
              <span class="text-primary font-mono text-xs font-semibold break-all" translate="no"
                >{tool.tool_name}</span
              >
              <span class="text-secondary text-xs" translate="no">{tool.mcp_server_name}</span>
            </span>
            {#if tool.tool_description}
              <span class="text-secondary line-clamp-2 text-xs leading-relaxed"
                >{tool.tool_description}</span
              >
            {/if}
          </li>
        {/each}
      </ul>
    </Popover.Content>
  </Popover.Root>
{/if}
