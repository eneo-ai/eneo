<script lang="ts">
  import { Handle, Position } from "@xyflow/svelte";

  export let data: {
    label: string;
    step: {
      step_order: number;
      input_type: string;
      output_type: string;
      mcp_policy: string;
      output_classification_override?: number | null;
    };
    isActive: boolean;
    mode: "user" | "power_user";
    runStatus?: string;
    numTokensInput?: number;
    numTokensOutput?: number;
    modelName?: string;
    classLevel?: number | null;
    assistantClassLevel?: number | null;
  };

  $: isPowerUser = data.mode === "power_user";

  $: borderColor = data.runStatus
    ? data.runStatus === "completed"
      ? "border-green-500"
      : data.runStatus === "failed"
        ? "border-red-500"
        : data.runStatus === "running"
          ? "border-blue-500"
          : "border-default"
    : data.isActive
      ? "border-blue-500"
      : "border-default";
</script>

{#if isPowerUser}
  <!-- Power User: Technical card -->
  <div
    class="bg-primary rounded-lg border-2 shadow-sm transition-colors {borderColor}"
    style="min-width: 200px;"
  >
    <div class="bg-hover-dimmer flex items-center justify-between px-3 py-1.5">
      <div class="flex items-center gap-2">
        <span class="bg-hover-default flex size-5 shrink-0 items-center justify-center rounded text-xs font-bold">
          {data.step.step_order}
        </span>
        <span class="truncate text-sm font-semibold">{data.label}</span>
      </div>
      <div class="flex items-center gap-1">
        {#if data.assistantClassLevel != null}
          <span class="rounded bg-accent-dimmer px-1.5 text-[10px] font-bold text-accent-stronger">
            Model K{data.assistantClassLevel}
          </span>
        {/if}
        {#if data.classLevel != null && data.classLevel !== data.assistantClassLevel}
          <span class="rounded px-1.5 text-[10px] font-bold
            {data.classLevel >= 3 ? 'bg-negative-dimmer text-negative-stronger' :
             data.classLevel >= 2 ? 'bg-warning-dimmer text-warning-stronger' :
             'bg-positive-dimmer text-positive-stronger'}">
            Output K{data.classLevel}
          </span>
        {/if}
      </div>
    </div>
    <div class="px-3 py-2 text-xs space-y-1">
      {#if data.modelName}
        <div class="text-secondary">{data.modelName}</div>
      {/if}
      <div class="flex items-center gap-1">
        <span class="bg-accent-dimmer text-accent-stronger rounded px-1.5">{data.step.input_type}</span>
        <span class="text-secondary">&rarr;</span>
        <span class="bg-positive-dimmer text-positive-stronger rounded px-1.5">{data.step.output_type}</span>
      </div>
      {#if data.step.mcp_policy === "restricted"}
        <div class="flex items-center gap-1 text-amber-600">
          MCP restricted
        </div>
      {/if}
      {#if data.runStatus && (data.numTokensInput || data.numTokensOutput)}
        <div class="text-secondary">
          {data.numTokensInput ?? 0} / {data.numTokensOutput ?? 0} tokens
        </div>
      {/if}
    </div>
  </div>
{:else}
  <!-- User Mode: Compact pill -->
  <div
    class="bg-primary flex items-center gap-2 rounded-lg border-2 px-3 py-1.5 shadow-sm transition-colors {borderColor}"
    style="min-width: 120px; max-width: 160px;"
  >
    <span class="bg-hover-default flex size-5 shrink-0 items-center justify-center rounded text-xs font-bold">
      {data.step.step_order}
    </span>
    <span class="truncate text-xs font-medium">{data.label}</span>
  </div>
{/if}

<Handle type="target" position={Position.Left} />
<Handle type="source" position={Position.Right} />
