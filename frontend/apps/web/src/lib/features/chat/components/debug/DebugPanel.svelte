<!--
  Copyright (c) 2026 Sundsvalls Kommun

  Licensed under the MIT License.

  Debug panel for the ongoing chat (deploy-flag gated). Shows, per turn, the
  full message chain the model worked with: the captured provider payload
  (rendered system prompt, replayed history, user question) followed by the
  turn's tool calls, tool results and final answer, reconstructed from the
  persisted turn in the same shape the next turn replays. Meta sections
  (model settings, knowledge references, tokens, raw payload) collapse below.
  Renders as an inline column next to the conversation so the chat stays
  usable while inspecting a live turn.
-->

<script lang="ts">
  import { getChatService } from "../../ChatService.svelte";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";
  import { downloadJson } from "$lib/core/helpers/downloadJson";
  import { CodeBlock } from "@eneo/ui";
  import { Download, X } from "lucide-svelte";
  import type { MessageLogging } from "@eneo/eneo-js";
  import DebugSection from "./DebugSection.svelte";
  import DebugChainEntry from "./DebugChainEntry.svelte";

  const chat = getChatService();

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

  // Captured payload for the selected turn: the persisted row once the turn
  // completed, or the payload streamed at turn start (debug_payload event)
  // while it is still running.
  const capturedDetails = $derived.by(() => {
    if (logging?.logging_details) return logging.logging_details;
    const live = chat.liveLoggingDetails;
    if (live && message?.id === live.messageId) return live.details;
    return null;
  });

  type ProviderToolCall = { id?: string; function?: { name?: string; arguments?: string } };
  type ProviderMessage = {
    role?: string;
    content?: unknown;
    tool_calls?: ProviderToolCall[];
  };
  const providerMessages = $derived.by(() => {
    const body = capturedDetails?.json_body;
    return Array.isArray(body) ? (body as ProviderMessage[]) : null;
  });

  const toolCalls = $derived(
    ((message as Record<string, unknown> | undefined)?.mcp_tool_calls ??
      message?.tool_calls ??
      []) as NonNullable<(typeof messages)[number]["tool_calls"]>
  );

  const stringify = (value: unknown) => JSON.stringify(value, null, 2);

  const contentToText = (content: unknown): string => {
    if (typeof content === "string") return content;
    if (Array.isArray(content)) {
      // Vision models carry content as block arrays; keep the text blocks.
      return content
        .map((block) => {
          if (block && typeof block === "object" && "text" in block) {
            return String(block.text ?? "");
          }
          if (block && typeof block === "object" && "image_url" in block) {
            return "[image]";
          }
          return "";
        })
        .join("");
    }
    return content == null ? "" : stringify(content);
  };

  const prettyArgs = (args: string | undefined) => {
    if (!args) return "";
    try {
      return stringify(JSON.parse(args));
    } catch {
      return args;
    }
  };

  // The chain: the captured turn-start payload (system prompt, replayed
  // history, user question) followed by this turn's tool rounds and final
  // answer, rebuilt from the persisted turn — the same shape the next turn's
  // replay sends. Without capture, the chain still shows question, tool
  // rounds and answer.
  type ChainEntry = {
    key: string;
    role: string;
    label?: string | null;
    content?: string | null;
    toolCallId?: string;
  };
  const chain = $derived.by<ChainEntry[]>(() => {
    const entries: ChainEntry[] = [];
    if (providerMessages) {
      providerMessages.forEach((entry, index) => {
        const role = entry.role ?? "?";
        const calls = entry.tool_calls ?? [];
        for (const [callIndex, call] of calls.entries()) {
          entries.push({
            key: `p${index}c${callIndex}`,
            role,
            label: `${m.debug_panel_tool_call()} · ${call.function?.name ?? "?"}`,
            content: prettyArgs(call.function?.arguments)
          });
        }
        const text = contentToText(entry.content);
        if (text || calls.length === 0) {
          entries.push({
            key: `p${index}`,
            role,
            label: role === "tool" ? m.debug_panel_tool_result() : null,
            content: text
          });
        }
      });
    } else if (message) {
      entries.push({ key: "question", role: "user", content: message.question });
    }
    toolCalls.forEach((toolCall, index) => {
      const name = toolCall.mcp_tool_name ?? toolCall.tool_name;
      entries.push({
        key: `call${index}`,
        role: "assistant",
        label: `${m.debug_panel_tool_call()} · ${name}`,
        content: toolCall.arguments ? stringify(toolCall.arguments) : ""
      });
      entries.push({
        key: `result${index}`,
        role: "tool",
        label: `${m.debug_panel_tool_result()} · ${name}`,
        content: toolCall.result ?? null,
        toolCallId: toolCall.tool_call_id ?? undefined
      });
    });
    if (message?.answer) {
      entries.push({ key: "answer", role: "assistant", content: message.answer });
    }
    return entries;
  });

  const tokenRows = $derived.by(() => {
    if (!message) return [];
    return [
      { label: m.question(), value: message.num_tokens_question },
      { label: m.answer(), value: message.num_tokens_answer },
      { label: m.context_size(), value: message.num_tokens_context }
    ].filter((row) => row.value != null);
  });

  async function downloadExport() {
    const id = chat.currentConversation.id;
    if (!id) return;
    try {
      const data = await chat.exportConversation({ id });
      const date = new Date().toISOString().slice(0, 10);
      downloadJson(`eneo-konversation-${id}-${date}.json`, data);
    } catch (error) {
      toastError(error);
    }
  }
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
      {#if isLiveTurn && !capturedDetails}
        <p class="text-muted px-3 py-2 text-xs">{m.debug_panel_capture_pending()}</p>
      {:else if !isLiveTurn && !loggingLoading && !capturedDetails}
        <p class="text-muted px-3 py-2 text-xs">{m.debug_panel_not_captured()}</p>
      {/if}

      <div class="border-dimmer flex flex-col gap-1.5 border-b px-3 py-2.5">
        <p class="text-default text-xs font-semibold">{m.debug_panel_chain()}</p>
        {#if toolCalls.length > 0 || message.answer}
          <p class="text-muted text-xs">{m.debug_panel_chain_reconstructed_note()}</p>
        {/if}
        {#each chain as entry (`${effectiveIndex}:${entry.key}`)}
          <DebugChainEntry
            role={entry.role}
            label={entry.label}
            content={entry.content}
            onLoadResult={entry.toolCallId
              ? () => chat.getToolCallResult(entry.toolCallId!)
              : undefined}
          />
        {/each}
      </div>

      {#if capturedDetails}
        <DebugSection title={m.debug_panel_model_settings()}>
          {#if message.completion_model?.name}
            <p class="text-default text-xs font-medium">{message.completion_model.name}</p>
          {/if}
          <CodeBlock
            source={stringify(capturedDetails.model_kwargs ?? {})}
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

      {#if capturedDetails}
        <DebugSection title={m.debug_panel_raw_payload()}>
          <p class="text-muted text-xs">{m.debug_panel_snapshot_note()}</p>
          <CodeBlock source={stringify(capturedDetails.json_body)} class="max-h-[50vh] text-xs" />
        </DebugSection>
      {/if}
    {/if}
  </div>

  {#if chat.currentConversation.id}
    <div class="border-dimmer border-t px-3 py-2">
      <button
        type="button"
        class="text-muted hover:text-default flex items-center gap-1.5 text-xs font-medium transition-colors"
        onclick={downloadExport}
      >
        <Download class="h-3.5 w-3.5 shrink-0" />
        {m.debug_panel_download_export()}
      </button>
    </div>
  {/if}
</aside>
