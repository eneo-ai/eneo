<script lang="ts">
  import { Badge } from "$lib/components/ui/badge/index.js";
  import AttachmentPreview from "$lib/features/attachments/components/AttachmentPreview.svelte";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import type { TurnDebugDetails } from "../../turnDebugProjection";
  import ChatDebugSection from "./ChatDebugSection.svelte";
  import CopyableDebugValue from "./CopyableDebugValue.svelte";

  let { details }: { details: TurnDebugDetails } = $props();
  const numberFormatter = $derived(new Intl.NumberFormat(getLocale() === "sv" ? "sv-SE" : "en-US"));
  const sentAtFormatter = $derived(
    new Intl.DateTimeFormat(getLocale() === "sv" ? "sv-SE" : "en-US", {
      dateStyle: "medium",
      timeStyle: "short"
    })
  );
  const sentAt = $derived.by(() => {
    if (!details.createdAt) return null;
    const parsed = new Date(details.createdAt);
    return Number.isNaN(parsed.getTime()) ? null : sentAtFormatter.format(parsed);
  });
</script>

<ChatDebugSection id="chat-debug-section-summary" title={m.chat_debug_generic_summary()}>
  <dl class="grid grid-cols-1 gap-x-5 gap-y-4 text-sm @md:grid-cols-2">
    <div class="min-w-0">
      <dt class="text-muted-foreground text-xs">{m.chat_debug_model()}</dt>
      <dd class="mt-0.5 font-medium break-words">
        {details.model?.name ?? m.chat_debug_unknown()}
      </dd>
    </div>
    {#if sentAt}
      <div>
        <dt class="text-muted-foreground text-xs">{m.chat_debug_sent_at()}</dt>
        <dd class="mt-0.5 font-medium tabular-nums">{sentAt}</dd>
      </div>
    {/if}
    <div>
      <dt class="text-muted-foreground text-xs">{m.chat_debug_input_tokens()}</dt>
      <dd class="mt-0.5 font-medium tabular-nums">
        {numberFormatter.format(details.inputTokens)}
      </dd>
    </div>
    <div>
      <dt class="text-muted-foreground text-xs">{m.chat_debug_output_tokens()}</dt>
      <dd class="mt-0.5 font-medium tabular-nums">
        {numberFormatter.format(details.outputTokens)}
      </dd>
    </div>
    {#if details.model}
      <CopyableDebugValue label={m.chat_debug_model_route()} value={details.model.route} />
      <CopyableDebugValue label={m.chat_debug_model_id()} value={details.model.id} />
    {/if}
  </dl>
</ChatDebugSection>

<ChatDebugSection
  id="chat-debug-section-tools"
  title={m.chat_debug_tools()}
  count={details.tools.length}
  defaultOpen={details.tools.length > 0}
>
  {#if details.tools.length === 0}
    <p class="text-muted-foreground text-sm">{m.chat_debug_no_tools()}</p>
  {:else}
    <ol class="flex flex-col gap-1">
      {#each details.tools as tool (tool.order)}
        <li class="border-border min-w-0 rounded-lg border px-3 py-2.5">
          <div class="flex min-w-0 items-start justify-between gap-3">
            <div class="min-w-0">
              <p class="text-sm font-medium break-words">
                <span class="text-muted-foreground tabular-nums"
                  >{m.chat_debug_tool_order({ order: String(tool.order) })}</span
                >
                · {tool.toolName}
              </p>
              <p class="text-muted-foreground mt-0.5 text-xs break-words">{tool.serverName}</p>
            </div>
            <Badge class="shrink-0" variant="outline">
              {tool.status ?? m.chat_debug_status_unknown()}
            </Badge>
          </div>
          {#if tool.usage}
            <dl
              class="border-border mt-2 grid grid-cols-2 gap-x-5 gap-y-2 border-t pt-2 text-sm"
              aria-label={m.chat_debug_tool_usage()}
            >
              {#if tool.usage.model}
                <div class="min-w-0">
                  <dt class="text-muted-foreground text-xs">{m.chat_debug_model()}</dt>
                  <dd class="mt-0.5 font-medium break-words">{tool.usage.model}</dd>
                </div>
              {/if}
              {#if tool.usage.provider}
                <div class="min-w-0">
                  <dt class="text-muted-foreground text-xs">{m.chat_debug_provider()}</dt>
                  <dd class="mt-0.5 font-medium break-words">{tool.usage.provider}</dd>
                </div>
              {/if}
              {#if tool.usage.inputTokens !== null}
                <div>
                  <dt class="text-muted-foreground text-xs">{m.chat_debug_input_tokens()}</dt>
                  <dd class="mt-0.5 font-medium tabular-nums">
                    {numberFormatter.format(tool.usage.inputTokens)}
                  </dd>
                </div>
              {/if}
              {#if tool.usage.outputTokens !== null}
                <div>
                  <dt class="text-muted-foreground text-xs">{m.chat_debug_output_tokens()}</dt>
                  <dd class="mt-0.5 font-medium tabular-nums">
                    {numberFormatter.format(tool.usage.outputTokens)}
                  </dd>
                </div>
              {/if}
            </dl>
          {/if}
        </li>
      {/each}
    </ol>
  {/if}
</ChatDebugSection>

<ChatDebugSection
  id="chat-debug-section-knowledge"
  title={m.chat_debug_knowledge()}
  count={details.knowledge.length}
  defaultOpen={details.knowledge.length > 0}
>
  {#if details.knowledge.length === 0}
    <p class="text-muted-foreground text-sm">{m.chat_debug_no_knowledge()}</p>
  {:else}
    <ol class="flex flex-col gap-1">
      {#each details.knowledge as reference (reference.order)}
        <li class="border-border min-w-0 rounded-lg border px-3 py-2.5">
          <p class="text-sm font-medium break-words">
            <span class="text-muted-foreground tabular-nums"
              >{m.chat_debug_reference_order({ order: String(reference.order) })}</span
            >
            · {reference.title}
          </p>
          {#if reference.uri}
            <dl class="mt-1.5">
              <CopyableDebugValue label={m.chat_debug_uri()} value={reference.uri} />
            </dl>
          {/if}
        </li>
      {/each}
    </ol>
  {/if}
</ChatDebugSection>

<ChatDebugSection
  id="chat-debug-section-files"
  title={m.chat_debug_files()}
  count={details.files.length}
  defaultOpen={details.files.length > 0}
>
  {#if details.files.length === 0}
    <p class="text-muted-foreground text-sm">{m.chat_debug_no_files()}</p>
  {:else}
    <ol class="flex flex-col gap-1">
      {#each details.files as file (file.order)}
        <li
          class="border-border flex min-w-0 items-start justify-between gap-3 rounded-lg border px-3 py-2.5"
        >
          <AttachmentPreview
            file={{ id: file.id, name: file.name, mimetype: file.mimetype, size: file.size }}
          >
            {#snippet children({ showFile })}
              <button
                type="button"
                class="text-primary min-w-0 text-left text-sm break-all underline-offset-2 hover:underline"
                aria-label={m.chat_debug_open_file({ name: file.name })}
                onclick={showFile}
              >
                {file.name}
              </button>
            {/snippet}
          </AttachmentPreview>
          <Badge class="shrink-0" variant="secondary">
            {file.kind === "input" ? m.chat_debug_file_input() : m.chat_debug_file_generated()}
          </Badge>
        </li>
      {/each}
    </ol>
  {/if}
</ChatDebugSection>
