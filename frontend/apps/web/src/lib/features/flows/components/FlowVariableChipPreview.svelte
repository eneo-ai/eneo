<script lang="ts">
  import type { FlowStep } from "@intric/intric-js";

  export let text: string;
  export let steps: FlowStep[];
  export let compact: boolean = false;

  type Segment = { type: "text"; value: string } | { type: "variable"; raw: string; label: string; color: string };

  $: segments = parseVariables(text);

  function parseVariables(input: string): Segment[] {
    const result: Segment[] = [];
    const regex = /\{\{\s*([^}]+)\s*\}\}/g;
    let lastIndex = 0;
    let match;

    while ((match = regex.exec(input)) !== null) {
      if (match.index > lastIndex) {
        result.push({ type: "text", value: input.slice(lastIndex, match.index) });
      }
      const raw = match[1].trim();
      const { label, color } = resolveVariable(raw);
      result.push({ type: "variable", raw: `{{ ${raw} }}`, label, color });
      lastIndex = regex.lastIndex;
    }

    if (lastIndex < input.length) {
      result.push({ type: "text", value: input.slice(lastIndex) });
    }

    return result;
  }

  function resolveVariable(variable: string): { label: string; color: string } {
    if (variable.startsWith("flow_input.") || variable.startsWith("flow.input.")) {
      const field = variable.split(".").pop() ?? variable;
      return { label: `Flow input: ${field}`, color: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300" };
    }

    const stepMatch = variable.match(/^step_(\d+)\./);
    if (stepMatch) {
      const order = parseInt(stepMatch[1], 10);
      const step = steps.find((s) => s.step_order === order);
      const name = step?.user_description ?? `Step ${order}`;
      // Clean up the field path for display — drop "output.structured." prefix
      let field = variable.replace(`step_${order}.`, "");
      if (field.startsWith("output.structured.")) {
        field = field.replace("output.structured.", "");
      } else if (field === "output") {
        field = "full output";
      } else if (field === "output.text") {
        field = "text";
      }
      const isStructured = variable.includes(".structured.");
      const color = isStructured
        ? "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300"
        : "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300";
      return { label: `${name}: ${field}`, color };
    }

    return { label: variable, color: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300" };
  }
</script>

{#if segments.some((s) => s.type === "variable")}
  <div class="flex flex-wrap items-center gap-1" class:text-xs={compact} class:py-1={!compact} class:py-0.5={compact}>
    {#each segments as segment}
      {#if segment.type === "text"}
        {#if !compact}
          <span class="text-secondary text-xs">{segment.value}</span>
        {/if}
      {:else}
        <span class="{segment.color} inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium">
          {segment.label}
        </span>
      {/if}
    {/each}
  </div>
{/if}
