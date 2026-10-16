<script lang="ts">
  import Plug from "@lucide/svelte/icons/plug";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { m } from "$lib/paraglide/messages";
  import type { BuilderToolArgument, BuilderToolStep } from "./builderToolStep";

  interface Props {
    toolStep: BuilderToolStep;
  }

  let { toolStep }: Props = $props();

  function earlierStepText(argument: Extract<BuilderToolArgument, { kind: "earlier_step" }>) {
    const order = String(argument.stepNumber);
    return argument.field === null
      ? m.flow_graph_tool_argument_from_step({ order })
      : m.flow_graph_tool_argument_from_step_field({ order, field: argument.field });
  }
</script>

<!-- The same facts the step editor and the flow graph show for a tool step:
     the server and tool, and where each argument comes from. -->
<div class="flex min-w-0 flex-col gap-1.5" data-testid="builder-tool-step">
  <p class="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 text-xs">
    <Plug class="text-secondary size-3.5 shrink-0" aria-hidden="true" />
    {#if toolStep.tool}
      <span class="text-secondary">{m.ai_builder_tool_step_fetches_from()}</span>
      <span class="text-primary font-semibold" translate="no">{toolStep.tool.serverName}</span>
      <span class="text-muted" aria-hidden="true">·</span>
      <span class="text-primary font-mono break-all" translate="no">{toolStep.tool.toolName}</span>
    {:else}
      <span class="text-warning-stronger">{m.ai_builder_tool_step_unknown()}</span>
    {/if}
    <Badge variant="outline" class="h-5 px-1.5 text-[0.6875rem]">{m.flow_graph_tool_badge()}</Badge>
  </p>
  {#if toolStep.arguments.length > 0}
    <dl
      class="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-xs"
      aria-label={m.ai_builder_tool_step_arguments()}
    >
      {#each toolStep.arguments as argument (argument.name)}
        <dt class="text-secondary truncate font-mono" translate="no" title={argument.name}>
          {argument.name}
        </dt>
        <dd class="min-w-0 break-words">
          {#if argument.kind === "fixed"}
            <span class="text-muted font-mono">{argument.text}</span>
          {:else if argument.kind === "run_input"}
            <span class="text-positive-stronger"
              >{m.ai_builder_tool_step_run_input({ label: argument.label })}</span
            >
          {:else if argument.kind === "earlier_step"}
            <span class="text-accent-stronger"
              ><span class="mr-1" aria-hidden="true">←</span>{earlierStepText(argument)}</span
            >
          {:else}
            <span class="text-secondary font-mono">{argument.text}</span>
          {/if}
        </dd>
      {/each}
    </dl>
  {/if}
  <p class="text-secondary text-xs">{m.ai_builder_tool_step_once()}</p>
</div>
