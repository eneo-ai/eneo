<script lang="ts">
  import { Markdown } from "@eneo/ui";
  import MessageEneoInfoBlob from "./MessageEneoInfoBlob.svelte";
  import McpImageAttachments from "./McpImageAttachments.svelte";
  import ReasoningTrace from "./ReasoningTrace.svelte";
  import InternalToolStep from "./InternalToolStep.svelte";
  import { dynamicColour } from "$lib/core/colours";
  import { IconSpeechBubble } from "@eneo/icons/speech-bubble";
  import { formatEmojiTitle } from "$lib/core/formatting/formatEmojiTitle";
  import { getChatService } from "../../ChatService.svelte";
  import {
    internalReadFileId,
    internalToolDoneLabel,
    isInternalServer,
    serverDisplayName,
    toolDisplayName
  } from "../../internalToolLabels";
  import { getAttachmentUrlService } from "$lib/features/attachments/AttachmentUrlService.svelte";
  import { getMessageContext } from "../../MessageContext.svelte";
  import AsyncImage from "$lib/components/AsyncImage.svelte";
  import { m } from "$lib/paraglide/messages";
  import { ChevronRight, Check, X, Wrench } from "lucide-svelte";
  import { SvelteMap, SvelteSet } from "svelte/reactivity";

  const chat = getChatService();
  const attachmentUrls = getAttachmentUrlService();

  const { current, isLast } = getMessageContext();
  const message = $derived(current());
  // Tools are still being executed if we're loading and no answer text has arrived yet
  const toolsStillExecuting = $derived(
    isLast() && chat.askQuestion.isLoading && message.answer.trim() === ""
  );
  // Looser gate than toolsStillExecuting: tool calls can interleave with answer
  // text (multi-round MCP), so "pending"/"approved" statuses stay live for the
  // whole streaming turn, not just until the first text chunk.
  const isStreamingTurn = $derived(isLast() && chat.askQuestion.isLoading);

  // Get MCP tool calls from the message
  // - mcp_tool_calls: runtime property added during streaming
  // - tool_calls: persisted field from API response (chat history)
  const mcpToolCalls = $derived(
    ((message as Record<string, unknown>).mcp_tool_calls ?? message.tool_calls) as
      | Array<{
          server_name: string;
          tool_name: string;
          title?: string | null;
          arguments?: Record<string, unknown>;
          tool_call_id?: string;
          approved?: boolean;
          result_status?: string;
        }>
      | undefined
  );

  // Reasoning/thinking text for this message: accumulated by ChatService while
  // streaming, served from the persisted `reasoning` field on reload.
  const reasoningText = $derived(
    ((message as Record<string, unknown>).reasoning as string | null | undefined) ?? ""
  );

  // Check if there's a pending tool approval for this message (only on last message)
  const hasPendingApproval = $derived(isLast() && chat.pendingToolApproval !== null);

  // Get pending tool IDs for matching
  const pendingToolIds = $derived(chat.pendingToolApproval?.tools.map((t) => t.tool_call_id) ?? []);

  // Check if there are multiple pending tools (for showing bulk actions)
  const hasMultiplePendingTools = $derived(pendingToolIds.length > 1);

  // Track which tool calls have expanded arguments
  const expandedToolCalls = new SvelteSet<number>();
  const submittingToolIds = new SvelteSet<string>();
  const deniedToolIds = new SvelteSet<string>();
  let isSubmittingBulk = $state(false);

  // Split tool calls: pending approvals stay as prominent cards below (a
  // blocking decision must never hide); everything else (running, done, denied)
  // folds into the collapsible reasoning trace above them.
  const isPending = (tc: { tool_call_id?: string }) =>
    !!tc.tool_call_id && pendingToolIds.includes(tc.tool_call_id);
  const pendingToolCalls = $derived((mcpToolCalls ?? []).filter(isPending));
  const tracedToolCalls = $derived((mcpToolCalls ?? []).filter((tc) => !isPending(tc)));

  // Attachment names across the whole conversation, so a read_file call on the
  // internal files server can be labelled with the file it is reading (its url
  // argument only carries the file id).
  const attachmentNamesById = $derived.by(() => {
    const names = new SvelteMap<string, string>();
    for (const msg of chat.currentConversation?.messages ?? []) {
      for (const file of msg.files ?? []) names.set(file.id, file.name);
    }
    return names;
  });
  const readFileDetail = (tc: {
    server_name: string;
    tool_name: string;
    arguments?: Record<string, unknown>;
  }) => {
    const fileId = internalReadFileId(tc.server_name, tc.tool_name, tc.arguments);
    return fileId ? (attachmentNamesById.get(fileId) ?? null) : null;
  };
  const tracedSteps = $derived(
    tracedToolCalls.map((tc, i) => {
      const denied =
        (!!tc.tool_call_id && deniedToolIds.has(tc.tool_call_id)) ||
        tc.approved === false ||
        tc.result_status === "denied" ||
        tc.result_status === "timeout_denied";
      const isLastTraced = i === tracedToolCalls.length - 1;
      // "pending" = the model is still writing the call's arguments;
      // "approved" = approved/auto-approved but the result hasn't landed yet.
      // A pending call on a turn that is no longer streaming never executed
      // (the stream died), so it is shown as failed rather than spinning forever.
      const status: "preparing" | "running" | "complete" | "failed" | "denied" = denied
        ? "denied"
        : tc.result_status === "failed"
          ? "failed"
          : tc.result_status === "pending"
            ? isStreamingTurn
              ? "preparing"
              : "failed"
            : tc.result_status === "approved" && isStreamingTurn
              ? "running"
              : toolsStillExecuting && isLastTraced
                ? "running"
                : "complete";
      const toolName = toolDisplayName(tc.tool_name, tc.server_name, tc.title, tc.arguments);
      return {
        // Eneo's own built-in tools get localized labels; otherwise prefer the
        // server-provided title annotation, falling back to the raw tool name.
        toolName,
        doneLabel: internalToolDoneLabel(tc.tool_name, tc.server_name, tc.arguments) ?? toolName,
        serverName: serverDisplayName(tc.server_name),
        detail: readFileDetail(tc),
        args: tc.arguments,
        toolCallId: tc.tool_call_id,
        status,
        internal: isInternalServer(tc.server_name)
      };
    })
  );
  // Built-in loopback tools render as slim thinking-style lines in the message
  // flow; only external MCP calls keep their cards in the reasoning trace.
  // Contiguous steps of the same kind group into runs that render in call
  // order, so the trace stays chronological when a turn mixes both kinds
  // (e.g. a knowledge search followed by web tools).
  const stepRuns = $derived.by(() => {
    const runs: { internal: boolean; steps: typeof tracedSteps }[] = [];
    for (const step of tracedSteps) {
      const last = runs[runs.length - 1];
      if (last && last.internal === step.internal) last.steps.push(step);
      else runs.push({ internal: step.internal, steps: [step] });
    }
    return runs;
  });

  // Internal steps take up a single line per run: while the assistant works,
  // only the run's latest step shows and each new call replaces the previous
  // one in place; once the run completes it folds into a one-line summary
  // that expands to the full list. A single step never folds — the summary
  // would be no smaller than the step itself. Runs only ever append during a
  // turn, so the run index is a stable key for the expanded state.
  const openInternalRuns = new SvelteSet<number>();
  const runWorking = (run: (typeof stepRuns)[number], runIndex: number) =>
    (toolsStillExecuting && runIndex === stepRuns.length - 1) ||
    run.steps.some((step) => step.status === "preparing" || step.status === "running");
  const runFailed = (run: (typeof stepRuns)[number]) =>
    run.steps.some((step) => step.status === "failed" || step.status === "denied");
  const runSummary = (run: (typeof stepRuns)[number]) => {
    const servers = [...new Set(run.steps.map((step) => step.serverName))].join(" · ");
    return `${servers} · ${m.internal_tool_steps_count({ count: run.steps.length })}`;
  };

  function toggleToolCallExpanded(index: number) {
    if (expandedToolCalls.has(index)) {
      expandedToolCalls.delete(index);
    } else {
      expandedToolCalls.add(index);
    }
  }

  async function handleApproveTool(toolCallId: string) {
    submittingToolIds.add(toolCallId);
    try {
      await chat.approveTool(toolCallId);
    } catch (error) {
      console.error("Failed to approve tool:", error);
    } finally {
      submittingToolIds.delete(toolCallId);
    }
  }

  async function handleDenyTool(toolCallId: string) {
    submittingToolIds.add(toolCallId);
    try {
      await chat.denyTool(toolCallId);
      deniedToolIds.add(toolCallId);
    } catch (error) {
      console.error("Failed to deny tool:", error);
    } finally {
      submittingToolIds.delete(toolCallId);
    }
  }

  async function handleApproveAll() {
    isSubmittingBulk = true;
    try {
      await chat.approveAllTools();
    } catch (error) {
      console.error("Failed to approve all tools:", error);
    } finally {
      isSubmittingBulk = false;
    }
  }

  async function handleDenyAll() {
    isSubmittingBulk = true;
    try {
      // Track all denied tools before clearing
      const toolIds =
        chat.pendingToolApproval?.tools.map((t) => t.tool_call_id).filter(Boolean) ?? [];
      await chat.rejectAllTools();
      toolIds.forEach((id) => deniedToolIds.add(id!));
    } catch (error) {
      console.error("Failed to deny all tools:", error);
    } finally {
      isSubmittingBulk = false;
    }
  }

  const showAnswerLabel = $derived.by(() => {
    let hasInfo = message.tools && message.tools.assistants.length > 0;
    let isSameAssistant = message.tools.assistants.some(({ id }) => id === chat.partner.id);
    let isEnabled =
      chat.partner.type === "default-assistant" ||
      ("show_response_label" in chat.partner && chat.partner.show_response_label);
    return hasInfo && !isSameAssistant && isEnabled;
  });
</script>

<div class="relative pt-4 text-lg">
  <span class="sr-only">{m.answer()}</span>
  {#if showAnswerLabel}
    {#each message.tools?.assistants ?? [] as mention (mention.id)}
      <div
        {...dynamicColour({ basedOn: mention.id })}
        class="bg-dynamic-dimmer text-dynamic-stronger mb-4 -ml-2 flex w-fit items-center gap-2 rounded-full px-4 py-2 text-base font-medium"
      >
        <IconSpeechBubble class="stroke-2"></IconSpeechBubble>
        <span>
          {formatEmojiTitle(mention.handle ?? m.unknown_assistant())}
        </span>
      </div>
    {/each}
  {/if}

  <!-- Reasoning text belongs at the top of the trace: it rides in the first
       run's box when that run is external, otherwise it gets its own box so
       it never renders below tool activity it preceded. -->
  {#if reasoningText.trim().length > 0 && (stepRuns.length === 0 || stepRuns[0].internal)}
    <div class="mb-4">
      <ReasoningTrace reasoning={reasoningText} working={toolsStillExecuting} />
    </div>
  {/if}

  {#each stepRuns as run, runIndex (runIndex)}
    {#if !run.internal}
      <div class="mb-4">
        <ReasoningTrace
          steps={run.steps}
          reasoning={runIndex === 0 ? reasoningText : ""}
          working={toolsStillExecuting && runIndex === stepRuns.length - 1}
          loadToolResult={(toolCallId) => chat.getToolCallResult(toolCallId)}
        />
      </div>
    {:else}
      {#snippet internalStepLines()}
        {#each run.steps as step, i (step.toolCallId ?? i)}
          <InternalToolStep
            runningLabel={step.toolName}
            doneLabel={step.doneLabel}
            serverName={step.serverName}
            detail={step.detail}
            args={step.args}
            toolCallId={step.toolCallId}
            status={step.status}
            onLoadResult={step.toolCallId
              ? () => chat.getToolCallResult(step.toolCallId!)
              : undefined}
          />
        {/each}
      {/snippet}
      <div class="mb-4 flex flex-col gap-0.5">
        {#if runWorking(run, runIndex)}
          {@const currentStep = run.steps[run.steps.length - 1]}
          <InternalToolStep
            runningLabel={currentStep.toolName}
            doneLabel={currentStep.doneLabel}
            serverName={currentStep.serverName}
            detail={currentStep.detail}
            args={currentStep.args}
            toolCallId={currentStep.toolCallId}
            status={currentStep.status}
            onLoadResult={currentStep.toolCallId
              ? () => chat.getToolCallResult(currentStep.toolCallId!)
              : undefined}
          />
        {:else if run.steps.length > 1}
          <button
            type="button"
            class="text-muted hover:text-secondary flex w-fit max-w-full items-center gap-1.5 text-sm leading-tight transition-colors"
            onclick={() =>
              openInternalRuns.has(runIndex)
                ? openInternalRuns.delete(runIndex)
                : openInternalRuns.add(runIndex)}
            aria-expanded={openInternalRuns.has(runIndex)}
          >
            <ChevronRight
              class="h-3.5 w-3.5 shrink-0 transition-transform {openInternalRuns.has(runIndex)
                ? 'rotate-90'
                : ''}"
            />
            {#if runFailed(run)}
              <X class="text-negative-default h-3.5 w-3.5 shrink-0" />
            {/if}
            <span class="truncate font-medium">{runSummary(run)}</span>
          </button>
          {#if openInternalRuns.has(runIndex)}
            <div class="flex flex-col gap-0.5 pl-7">
              {@render internalStepLines()}
            </div>
          {/if}
        {:else}
          {@render internalStepLines()}
        {/if}
      </div>
    {/if}
  {/each}

  {#if pendingToolCalls.length > 0}
    <div class="mb-5 flex flex-col gap-2">
      {#each pendingToolCalls as toolCall, idx (toolCall.tool_call_id ?? idx)}
        {@const isLastToolCall = idx === pendingToolCalls.length - 1}
        {@const isPendingTool =
          toolCall.tool_call_id && pendingToolIds.includes(toolCall.tool_call_id)}
        {@const isDeniedLocally = toolCall.tool_call_id && deniedToolIds.has(toolCall.tool_call_id)}
        {@const isDeniedFromBackend = toolCall.approved === false}
        {@const isDenied = isDeniedLocally || isDeniedFromBackend}
        {@const isApproved = toolCall.approved === true}
        {@const shouldPulse = isLastToolCall && toolsStillExecuting && !hasPendingApproval}
        {@const hasArgs = toolCall.arguments && Object.keys(toolCall.arguments).length > 0}
        {@const isExpanded = expandedToolCalls.has(idx)}
        {@const isSubmitting = toolCall.tool_call_id
          ? submittingToolIds.has(toolCall.tool_call_id)
          : false}
        {@const pendingDetail = readFileDetail(toolCall)}
        {@const statusStyle = isDenied
          ? "border-negative-default/20 bg-negative-dimmer/50"
          : isApproved
            ? "border-positive-default/20 bg-positive-dimmer/50"
            : "border-default bg-secondary/80"}
        <div
          class="group rounded-lg border {statusStyle} transition-all duration-200 {shouldPulse
            ? 'animate-pulse'
            : ''}"
        >
          <!-- Tool header -->
          <button
            type="button"
            class="flex w-full items-center gap-3 px-3 py-2.5 text-left {hasArgs
              ? 'cursor-pointer'
              : 'cursor-default'}"
            onclick={() => hasArgs && toggleToolCallExpanded(idx)}
            disabled={!hasArgs}
          >
            <!-- Status indicator -->
            <div
              class="flex h-8 w-8 shrink-0 items-center justify-center rounded-md {isDenied
                ? 'bg-negative-default/10 text-negative-default'
                : isApproved
                  ? 'bg-positive-default/10 text-positive-default'
                  : 'bg-accent-default/10 text-accent-default'}"
            >
              <Wrench class="h-4 w-4" />
            </div>

            <!-- Tool info -->
            <div class="flex min-w-0 flex-1 flex-col gap-0.5">
              <div class="flex items-center gap-2">
                <span class="text-default truncate text-sm font-medium"
                  >{toolDisplayName(toolCall.tool_name, toolCall.server_name)}</span
                >
                {#if pendingDetail}
                  <span class="text-muted min-w-0 truncate text-xs">{pendingDetail}</span>
                {/if}
                {#if isDenied}
                  <span
                    class="bg-negative-dimmer text-negative-default inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium tracking-wide uppercase"
                  >
                    {m.tool_rejected_by_user()}
                  </span>
                {:else if isApproved}
                  <span
                    class="bg-positive-dimmer text-positive-default inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium tracking-wide uppercase"
                  >
                    <Check class="h-2.5 w-2.5" />
                  </span>
                {/if}
              </div>
              <span class="text-muted text-xs">{toolCall.server_name}</span>
            </div>

            <!-- Expand indicator -->
            {#if hasArgs}
              <ChevronRight
                class="text-muted h-4 w-4 shrink-0 transition-transform duration-200 {isExpanded
                  ? 'rotate-90'
                  : ''}"
              />
            {/if}
          </button>

          <!-- Expanded arguments -->
          {#if hasArgs && isExpanded}
            <div class="border-dimmer border-t px-3 py-2.5">
              <div class="bg-primary/60 rounded-md p-3">
                <pre
                  class="text-secondary overflow-x-auto font-mono text-xs leading-relaxed break-words whitespace-pre-wrap">{JSON.stringify(
                    toolCall.arguments,
                    null,
                    2
                  )}</pre>
              </div>
            </div>
          {/if}

          <!-- Approval actions -->
          {#if isPendingTool && toolCall.tool_call_id}
            <div class="border-dimmer flex items-center gap-2 border-t px-3 py-2.5">
              <span class="text-muted mr-auto text-xs">{m.chat_tool_awaiting_approval()}</span>
              <button
                type="button"
                class="bg-positive-default text-on-fill hover:bg-positive-stronger inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium shadow-sm transition-colors disabled:opacity-50"
                onclick={() => handleApproveTool(toolCall.tool_call_id!)}
                disabled={isSubmitting}
              >
                <Check class="h-3.5 w-3.5" />
                {m.tool_accept()}
              </button>
              <button
                type="button"
                class="border-default bg-primary text-secondary hover:bg-hover-default inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium shadow-sm transition-colors disabled:opacity-50"
                onclick={() => handleDenyTool(toolCall.tool_call_id!)}
                disabled={isSubmitting}
              >
                <X class="h-3.5 w-3.5" />
                {m.tool_deny()}
              </button>
            </div>
          {/if}
        </div>
      {/each}

      <!-- Bulk approval actions -->
      {#if hasPendingApproval && hasMultiplePendingTools}
        <div
          class="border-default bg-secondary/50 mt-1 flex items-center justify-end gap-2 rounded-lg border border-dashed px-3 py-2.5"
        >
          <span class="text-muted mr-auto text-xs"
            >{m.chat_tools_pending({ count: pendingToolIds.length })}</span
          >
          <button
            type="button"
            class="bg-positive-default text-on-fill hover:bg-positive-stronger inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium shadow-sm transition-colors disabled:opacity-50"
            onclick={handleApproveAll}
            disabled={isSubmittingBulk}
          >
            <Check class="h-3.5 w-3.5" />
            {m.tool_accept_all({ count: pendingToolIds.length })}
          </button>
          <button
            type="button"
            class="border-default bg-primary text-secondary hover:bg-hover-default inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium shadow-sm transition-colors disabled:opacity-50"
            onclick={handleDenyAll}
            disabled={isSubmittingBulk}
          >
            <X class="h-3.5 w-3.5" />
            {m.tool_deny_all()}
          </button>
        </div>
      {/if}
    </div>
  {/if}

  <Markdown
    source={message.answer}
    customRenderers={{
      inref: MessageEneoInfoBlob
    }}
  />
</div>

<McpImageAttachments />

{#each message.generated_files as file (file.id)}
  {@const url = attachmentUrls.getUrl(file) ?? null}
  <AsyncImage {url}></AsyncImage>
{/each}
