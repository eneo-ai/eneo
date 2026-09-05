<script lang="ts">
  import { Wrench } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import type { components } from "@eneo/eneo-js";

  let { tools }: { tools: components["schemas"]["MCPServerToolPublic"][] } = $props();
</script>

<section class="border-dimmer bg-secondary/20 mt-4 rounded-lg border p-4" aria-label={m.tools()}>
  <h4 class="text-secondary mb-3 flex items-center gap-2 text-xs font-medium">
    <Wrench class="h-3.5 w-3.5" aria-hidden="true" />
    {m.tools()} <span class="tabular-nums">({tools.length})</span>
  </h4>
  {#if tools.length}
    <ul class="space-y-3">
      {#each tools as tool (tool.id)}
        <li class="flex flex-wrap items-start justify-between gap-2">
          <div class="min-w-0 flex-1">
            <p class="text-default text-sm font-medium">
              {tool.display_name ?? tool.title ?? tool.name}
            </p>
            {#if tool.description}
              <p class="text-secondary mt-1 text-sm">{tool.description.split(/\n\s*\n/)[0]}</p>
            {/if}
          </div>
          <span
            class="rounded-full px-2 py-0.5 text-xs {tool.is_enabled_by_default
              ? 'bg-positive-dimmer text-positive-stronger'
              : 'bg-secondary text-secondary'}"
          >
            {tool.is_enabled_by_default ? m.enabled() : m.disabled()}
          </span>
        </li>
      {/each}
    </ul>
  {:else}
    <p class="text-secondary text-sm">{m.no_tools_found()}</p>
  {/if}
</section>
