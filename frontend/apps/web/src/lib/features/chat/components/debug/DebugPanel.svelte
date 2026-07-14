<!--
  Copyright (c) 2026 Sundsvalls Kommun

  Licensed under the MIT License.

  Debug panel for the ongoing chat (deploy-flag gated). Shows, per turn, what
  the model actually received: the rendered system prompt and provider message
  array (captured server-side when the turn is asked with debug=true),
  model settings, knowledge references, tool calls with lazily loaded
  results, and token counts. Renders as an inline column next to the
  conversation so the chat stays usable while inspecting a live turn.
-->

<script lang="ts">
  import { getChatService } from "../../ChatService.svelte";
  import { m } from "$lib/paraglide/messages";
  import { CodeBlock } from "@eneo/ui";
  import { ChevronRight, X } from "lucide-svelte";
  import type { MessageLogging } from "@eneo/eneo-js";
  import { SvelteSet } from "svelte/reactivity";
  import DebugSection from "./DebugSection.svelte";
  import ToolCallDetailsPanel from "../conversation/ToolCallDetailsPanel.svelte";
  import { toolDisplayName } from "../../internalToolLabels";

  const chat = getChatService();

  // Expanded tool calls, keyed per turn + call so switching turns collapses.
  const expandedToolCalls = new SvelteSet<string>();
  const toggleToolCall = (key: string) =>
    expandedToolCalls.has(key) ? expandedToolCalls.delete(key) : expandedToolCalls.add(key);

  const messages = $derived(chat.currentConversation.messages ?? []);

  // Turn selection: no pick (or a pick from another conversation) follows the
  // latest turn, so the panel tracks a live stream by default. Binding the
  // pick to the conversation id makes it self-invalidate on switch without an
  // effect.
  let selected = $state<{ conversationId: string | null; index: number } | null>(null);
  const effectiveIndex = $derived.by(() => {
    const valid =
      selected !== null &&
      selected.conversationId === chat.currentConversation.id &&
      selected.index < messages.length;
    return valid && selected !== null ? selected.index : messages.length - 1;
  });
  const message = $derived(effectiveIndex >= 0 ? messages[effectiveIndex] : undefined);
  const isLiveTurn = $derived(effectiveIndex === messages.length - 1 && chat.askQuestion.isLoading);

  // Captured provider payload for the selected turn. Only fetched once the
  // turn has completed — the logging row is persisted with the answer.
  let logging = $state<MessageLogging | null>(null);
  let loggingLoading = $state(false);
  $effect(() => {
    const id = message?.id;
    if (!id || isLiveTurn) {
      logging = null;
      loggingLoading = false;
      return;
    }
    let stale = false;
    loggingLoading = true;
    chat.getLoggingDetails(id).then((result) => {
      if (stale) return;
      logging = result;
      loggingLoading = false;
    });
    return () => {
      stale = true;
    };
  });

  type ProviderMessage = { role?: string; content?: unknown };
  const providerMessages = $derived.by(() => {
    const body = logging?.logging_details?.json_body;
    return Array.isArray(body) ? (body as ProviderMessage[]) : null;
  });
  const systemPrompt = $derived.by(() => {
    const system = providerMessages?.find((entry) => entry.role === "system");
    if (!system) return null;
    if (typeof system.content === "string") return system.content;
    // Vision models carry content as block arrays; keep the text blocks.
    if (Array.isArray(system.content)) {
      return system.content
        .map((block) => (typeof block === "object" && block && "text" in block ? block.text : ""))
        .join("");
    }
    return null;
  });

  const toolCalls = $derived(
    ((message as Record<string, unknown> | undefined)?.mcp_tool_calls ??
      message?.tool_calls ??
      []) as NonNullable<(typeof messages)[number]["tool_calls"]>
  );

  const tokenRows = $derived.by(() => {
    if (!message) return [];
    return [
      { label: m.question(), value: message.num_tokens_question },
      { label: m.answer(), value: message.num_tokens_answer },
      { label: m.context_size(), value: message.num_tokens_context }
    ].filter((row) => row.value != null);
  });

  const stringify = (value: unknown) => JSON.stringify(value, null, 2);
</script>

<aside
  class="border-default bg-primary flex h-full w-[380px] shrink-0 flex-col border-l xl:w-[460px]"
  aria-label={m.debug_panel_title()}
>
  <div class="border-dimmer flex items-center gap-2 border-b px-3 py-2">
    <span class="text-default text-sm font-semibold">{m.debug_panel_title()}</span>
    {#if messages.length > 0}
      <select
        class="border-default bg-primary text-default min-w-0 flex-1 truncate rounded-md border px-2 py-1 text-sm"
        value={effectiveIndex}
        onchange={(event) =>
          (selected = {
            conversationId: chat.currentConversation.id,
            index: Number(event.currentTarget.value)
          })}
      >
        {#each messages as turn, index (index)}
          <option value={index}>
            {m.debug_panel_turn_label({ number: index + 1 })} · {turn.question}
          </option>
        {/each}
      </select>
    {/if}
    <button
      type="button"
      class="text-muted hover:text-default ml-auto shrink-0 transition-colors"
      onclick={() => chat.toggleDebugPanel()}
      aria-label={m.debug_panel_hide()}
    >
      <X class="h-4 w-4" />
    </button>
  </div>

  <div class="min-h-0 flex-1 overflow-y-auto">
    {#if !message}
      <p class="text-muted px-3 py-4 text-sm">{m.debug_panel_no_messages()}</p>
    {:else}
      {#if isLiveTurn}
        <p class="text-muted px-3 py-2 text-xs">{m.debug_panel_capture_pending()}</p>
      {:else if !loggingLoading && !logging?.logging_details}
        <p class="text-muted px-3 py-2 text-xs">{m.debug_panel_not_captured()}</p>
      {/if}

      {#if logging?.logging_details}
        <DebugSection title={m.debug_panel_system_prompt()} defaultOpen={true}>
          {#if systemPrompt}
            <pre
              class="border-dimmer bg-secondary/40 max-h-80 overflow-auto rounded-md border p-2 text-xs whitespace-pre-wrap">{systemPrompt}</pre>
          {:else}
            <p class="text-muted text-xs">{m.debug_panel_empty_section()}</p>
          {/if}
        </DebugSection>

        <DebugSection
          title={m.debug_panel_provider_messages()}
          count={providerMessages?.length ?? null}
        >
          <p class="text-muted text-xs">{m.debug_panel_snapshot_note()}</p>
          <CodeBlock
            source={stringify(logging.logging_details.json_body)}
            class="max-h-[50vh] text-xs"
          />
        </DebugSection>

        <DebugSection title={m.debug_panel_model_settings()}>
          {#if message.completion_model?.name}
            <p class="text-default text-xs font-medium">{message.completion_model.name}</p>
          {/if}
          <CodeBlock
            source={stringify(logging.logging_details.model_kwargs ?? {})}
            class="max-h-60 text-xs"
          />
        </DebugSection>
      {/if}

      <DebugSection
        title={m.debug_panel_knowledge()}
        count={(message.references?.length ?? 0) + (message.mcp_tool_references?.length ?? 0)}
      >
        {#if message.references?.length}
          <ul class="flex flex-col gap-1">
            {#each message.references as reference (reference.id)}
              <li class="text-default truncate text-xs">
                {reference.metadata.title ?? reference.id}
              </li>
            {/each}
          </ul>
        {/if}
        {#if message.mcp_tool_references?.length}
          <ul class="flex flex-col gap-1">
            {#each message.mcp_tool_references as reference (reference.id)}
              <li class="text-muted truncate text-xs">{reference.uri}</li>
            {/each}
          </ul>
        {/if}
        {#if !message.references?.length && !message.mcp_tool_references?.length}
          <p class="text-muted text-xs">{m.debug_panel_empty_section()}</p>
        {/if}
      </DebugSection>

      <DebugSection title={m.debug_panel_tools()} count={toolCalls.length}>
        {#if toolCalls.length === 0}
          <p class="text-muted text-xs">{m.debug_panel_empty_section()}</p>
        {:else}
          {#each toolCalls as toolCall, index (toolCall.tool_call_id ?? index)}
            {@const key = `${effectiveIndex}:${toolCall.tool_call_id ?? index}`}
            {@const displayName = toolDisplayName(
              toolCall.tool_name,
              toolCall.server_name,
              toolCall.title,
              toolCall.arguments ?? undefined
            )}
            <div class="border-dimmer rounded-md border">
              <button
                type="button"
                class="text-default flex w-full items-center gap-1.5 px-2 py-1.5 text-xs font-medium"
                onclick={() => toggleToolCall(key)}
                aria-expanded={expandedToolCalls.has(key)}
              >
                <ChevronRight
                  class="text-muted h-3 w-3 shrink-0 transition-transform {expandedToolCalls.has(
                    key
                  )
                    ? 'rotate-90'
                    : ''}"
                />
                <span class="truncate">{displayName}</span>
                <span class="text-muted shrink-0 font-normal">· {toolCall.server_name}</span>
              </button>
              <ToolCallDetailsPanel
                open={expandedToolCalls.has(key)}
                toolName={displayName}
                args={toolCall.arguments ?? undefined}
                toolCallId={toolCall.tool_call_id ?? undefined}
                onLoadResult={toolCall.tool_call_id
                  ? () => chat.getToolCallResult(toolCall.tool_call_id!)
                  : undefined}
              />
            </div>
          {/each}
        {/if}
      </DebugSection>

      {#if message.reasoning}
        <DebugSection title={m.reasoning()}>
          <pre
            class="border-dimmer bg-secondary/40 max-h-80 overflow-auto rounded-md border p-2 text-xs whitespace-pre-wrap">{message.reasoning}</pre>
        </DebugSection>
      {/if}

      <DebugSection title={m.debug_panel_tokens()} count={tokenRows.length || null}>
        {#if tokenRows.length === 0}
          <p class="text-muted text-xs">{m.debug_panel_empty_section()}</p>
        {:else}
          <ul class="flex flex-col gap-1">
            {#each tokenRows as row (row.label)}
              <li class="text-default flex justify-between text-xs">
                <span>{row.label}</span>
                <span class="tabular-nums">{row.value?.toLocaleString()}</span>
              </li>
            {/each}
          </ul>
        {/if}
      </DebugSection>
    {/if}
  </div>
</aside>
