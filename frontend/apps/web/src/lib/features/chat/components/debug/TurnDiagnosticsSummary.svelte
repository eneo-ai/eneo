<script lang="ts">
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Separator } from "$lib/components/ui/separator/index.js";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import type { TurnDebugDetails } from "../../turnDebugProjection";
  import CopyableDebugValue from "./CopyableDebugValue.svelte";

  let { details }: { details: TurnDebugDetails } = $props();
  const numberFormatter = $derived(new Intl.NumberFormat(getLocale() === "sv" ? "sv-SE" : "en-US"));
</script>

<section class="flex flex-col gap-4 px-5 py-5" aria-labelledby="chat-debug-turn-summary">
  <div class="flex items-baseline justify-between gap-3">
    <h2 id="chat-debug-turn-summary" class="text-sm font-semibold">
      {m.chat_debug_generic_summary()}
    </h2>
    <span class="text-muted-foreground text-xs">
      {m.chat_debug_turn_counts({
        tools: String(details.tools.length),
        knowledge: String(details.knowledge.length),
        files: String(details.files.length)
      })}
    </span>
  </div>

  <dl class="grid grid-cols-2 gap-x-5 gap-y-4 text-sm">
    <div class="min-w-0">
      <dt class="text-muted-foreground text-xs">{m.chat_debug_model()}</dt>
      <dd class="mt-0.5 break-words font-medium">
        {details.model?.name ?? m.chat_debug_unknown()}
      </dd>
    </div>
    <div>
      <dt class="text-muted-foreground text-xs">{m.chat_debug_input_tokens()}</dt>
      <dd class="mt-0.5 font-medium tabular-nums">{numberFormatter.format(details.inputTokens)}</dd>
    </div>
    <div>
      <dt class="text-muted-foreground text-xs">{m.chat_debug_output_tokens()}</dt>
      <dd class="mt-0.5 font-medium tabular-nums">
        {numberFormatter.format(details.outputTokens)}
      </dd>
    </div>
    {#if details.model}
      <CopyableDebugValue label={m.chat_debug_model_id()} value={details.model.id} />
      <CopyableDebugValue label={m.chat_debug_model_route()} value={details.model.route} />
    {/if}
  </dl>
</section>

<Separator />

<section class="flex flex-col gap-3 px-5 py-5" aria-labelledby="chat-debug-tools">
  <h2 id="chat-debug-tools" class="text-sm font-semibold">{m.chat_debug_tools()}</h2>
  {#if details.tools.length === 0}
    <p class="text-muted-foreground text-sm">{m.chat_debug_no_tools()}</p>
  {:else}
    <ol class="border-border border-t">
      {#each details.tools as tool (tool.order)}
        <li class="border-border flex min-w-0 items-start justify-between gap-3 border-b py-3">
          <div class="min-w-0">
            <p class="break-words text-sm font-medium">
              {m.chat_debug_tool_order({ order: String(tool.order) })}: {tool.toolName}
            </p>
            <p class="text-muted-foreground mt-0.5 break-words text-xs">{tool.serverName}</p>
          </div>
          <Badge class="shrink-0" variant="outline">
            {tool.status ?? m.chat_debug_status_unknown()}
          </Badge>
        </li>
      {/each}
    </ol>
  {/if}
</section>

<Separator />

<section class="flex flex-col gap-3 px-5 py-5" aria-labelledby="chat-debug-knowledge">
  <h2 id="chat-debug-knowledge" class="text-sm font-semibold">{m.chat_debug_knowledge()}</h2>
  {#if details.knowledge.length === 0}
    <p class="text-muted-foreground text-sm">{m.chat_debug_no_knowledge()}</p>
  {:else}
    <ol class="border-border border-t">
      {#each details.knowledge as reference (reference.order)}
        <li class="border-border min-w-0 border-b py-3">
          <p class="break-words text-sm font-medium">
            {m.chat_debug_reference_order({ order: String(reference.order) })}: {reference.title}
          </p>
          {#if reference.uri}
            <dl class="mt-1">
              <CopyableDebugValue label={m.chat_debug_uri()} value={reference.uri} />
            </dl>
          {/if}
        </li>
      {/each}
    </ol>
  {/if}
</section>

<Separator />

<section class="flex flex-col gap-3 px-5 py-5" aria-labelledby="chat-debug-files">
  <h2 id="chat-debug-files" class="text-sm font-semibold">{m.chat_debug_files()}</h2>
  {#if details.files.length === 0}
    <p class="text-muted-foreground text-sm">{m.chat_debug_no_files()}</p>
  {:else}
    <ol class="border-border border-t">
      {#each details.files as file (file.order)}
        <li class="border-border flex min-w-0 items-start justify-between gap-3 border-b py-3">
          <span class="break-all text-sm">{file.name}</span>
          <Badge class="shrink-0" variant="secondary">
            {file.kind === "input" ? m.chat_debug_file_input() : m.chat_debug_file_generated()}
          </Badge>
        </li>
      {/each}
    </ol>
  {/if}
</section>
