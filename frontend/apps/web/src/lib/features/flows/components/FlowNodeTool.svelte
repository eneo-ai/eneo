<script lang="ts">
  import { Handle, Position } from "@xyflow/svelte";
  import Plug from "@lucide/svelte/icons/plug";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import { cn } from "$lib/utils.js";
  import { m } from "$lib/paraglide/messages";
  import { toolRefusalSentence } from "$lib/features/flows/flowToolRefusal";
  import {
    TOOL_NODE_COMPACT_HEIGHT,
    TOOL_NODE_MORE_HANDLE,
    TOOL_NODE_WIDTH,
    argumentHasEdge,
    toolNodeGeometry,
    type FlowGraphToolArgument,
    type FlowGraphToolNode
  } from "$lib/features/flows/flowGraphToolNode";

  let {
    data
  }: {
    data: {
      tool: FlowGraphToolNode;
      mode: "user" | "power_user";
      /** Argument rows an emphasised binding edge ends at. */
      litArguments?: string[];
      dimmed?: boolean;
      lifted?: boolean;
    };
  } = $props();

  const tool = $derived(data.tool);
  const detailed = $derived(data.mode === "power_user");
  const geometry = $derived(toolNodeGeometry(tool));
  const serverLabel = $derived(tool.serverName ?? m.flow_graph_tool_fallback());
  const toolLabel = $derived(tool.toolName ?? m.flow_graph_tool_unknown_name());
  const problemText = $derived.by((): string | null => {
    switch (tool.problem?.kind) {
      case "unchosen":
        return m.flow_graph_tool_unchosen_hint();
      case "not_listed":
        return m.flow_tool_stored_missing();
      case "refused":
        return toolRefusalSentence(tool.problem.refusal);
      default:
        return null;
    }
  });
  // A tool the editor knows a run cannot call is drawn as broken, not as fine.
  const isBroken = $derived(
    tool.problem?.kind === "not_listed" || tool.problem?.kind === "refused"
  );

  function boundText(row: FlowGraphToolArgument): string {
    if (row.kind !== "step") return row.text;
    return row.field === null
      ? m.flow_graph_tool_argument_from_step({ order: String(row.stepOrder) })
      : m.flow_graph_tool_argument_from_step_field({
          order: String(row.stepOrder),
          field: row.field
        });
  }
</script>

<div
  class={cn(
    "flow-node flow-tool-node bg-primary text-primary flex flex-col overflow-hidden rounded-lg border border-dashed shadow-xs",
    isBroken ? "border-warning-default bg-warning-dimmer/40" : "border-strongest",
    // A broken tool keeps full contrast: its warning matters most when the
    // reader is looking elsewhere.
    data.dimmed && !isBroken && "is-dimmed",
    data.lifted && "is-lifted"
  )}
  style:width="{detailed ? TOOL_NODE_WIDTH : 200}px"
  style:height="{detailed ? geometry.height : TOOL_NODE_COMPACT_HEIGHT}px"
>
  {#if detailed}
    <div class="border-default flex h-8 shrink-0 items-center gap-1.5 border-b border-dashed px-3">
      <Plug class="text-secondary size-3.5 shrink-0" aria-hidden="true" />
      <span class="truncate text-xs font-semibold" title={serverLabel}>{serverLabel}</span>
      <Badge variant="outline" class="ml-auto shrink-0 px-1.5 text-[10px]">
        {m.flow_graph_tool_badge()}
      </Badge>
    </div>
    <div class="flex flex-col px-3 py-2">
      <div class="flex h-[22px] items-center">
        {#if tool.problem?.kind === "unchosen"}
          <span class="text-secondary truncate text-xs">{m.flow_graph_tool_unchosen()}</span>
        {:else if tool.listState === "loading" && tool.toolName === null}
          <Skeleton class="h-3 w-32" />
        {:else}
          <span class="truncate font-mono text-xs font-semibold" title={toolLabel}>{toolLabel}</span
          >
        {/if}
      </div>
      {#each tool.rows as row (row.name)}
        <div
          class={cn(
            "-mx-1.5 flex h-5 min-w-0 items-center gap-1 rounded px-1.5 font-mono text-[11px] transition-colors duration-200 ease-out motion-reduce:transition-none",
            argumentHasEdge(row) && "text-accent-stronger",
            // A reference that reads nothing: no edge reaches it, so it is not drawn as bound.
            row.kind === "unresolved" && "text-warning-stronger",
            data.litArguments?.includes(row.name) && "bg-accent-dimmer"
          )}
          title="{row.name}: {boundText(row)}"
        >
          <span class="text-secondary shrink-0">{row.name}</span>
          <span class="text-muted shrink-0" aria-hidden="true"
            >{argumentHasEdge(row) ? "←" : "="}</span
          >
          <span class={cn("truncate", row.kind === "fixed" && "text-muted")}>{boundText(row)}</span>
        </div>
      {/each}
      {#if tool.hiddenCount > 0}
        <div class="text-muted flex h-5 items-center text-[11px]">
          {m.flow_graph_tool_more_arguments({ count: String(tool.hiddenCount) })}
        </div>
      {/if}
      {#if problemText !== null}
        <div
          class={cn(
            "flex h-5 min-w-0 items-center gap-1 text-[11px]",
            isBroken ? "text-warning-stronger" : "text-muted"
          )}
          title={problemText}
        >
          {#if isBroken}
            <TriangleAlert class="size-3 shrink-0" aria-hidden="true" />
          {/if}
          <span class="truncate">{problemText}</span>
        </div>
      {/if}
    </div>
  {:else}
    <div class="flex h-full min-w-0 items-center gap-2 px-3">
      {#if isBroken}
        <TriangleAlert class="text-warning-stronger size-3.5 shrink-0" aria-hidden="true" />
      {:else}
        <Plug class="text-secondary size-3.5 shrink-0" aria-hidden="true" />
      {/if}
      <div class="flex min-w-0 flex-col">
        <span class="truncate text-xs font-medium" title={tool.toolName ?? serverLabel}>
          {tool.toolName ?? serverLabel}
        </span>
        {#if tool.toolName !== null}
          <span class="text-secondary truncate text-[11px]">{serverLabel}</span>
        {/if}
      </div>
    </div>
  {/if}
</div>

{#if detailed}
  {#each tool.rows as row, index (row.name)}
    {#if argumentHasEdge(row)}
      <Handle
        type="target"
        id="arg:{row.name}"
        position={Position.Left}
        style="top: {geometry.rowCenterY(index)}px"
      />
    {/if}
  {/each}
  {#if tool.hiddenCount > 0}
    <Handle
      type="target"
      id={TOOL_NODE_MORE_HANDLE}
      position={Position.Left}
      style="top: {geometry.moreCenterY}px"
    />
  {/if}
{:else}
  <Handle type="target" id={TOOL_NODE_MORE_HANDLE} position={Position.Left} />
{/if}
<Handle type="source" position={Position.Bottom} />
