<script lang="ts">
  import { analysisStep } from "../../analysisStep";
  import { analysisStepLabels } from "../../analysisStepLabels";
  import { toolFileInputs, type ToolInputFile } from "../../toolFileInputs";
  import { previousToolAttemptIndexes, toolStepStatus } from "../../toolStepStatus";
  import { Markdown } from "$lib/components/markdown/index.js";
  import MessageEneoInfoBlob from "./MessageEneoInfoBlob.svelte";
  import MessageDocumentLink from "./MessageDocumentLink.svelte";
  import McpImageAttachments from "./McpImageAttachments.svelte";
  import {
    appViewCalls,
    appViewSubject,
    appViewTitle,
    isChartDocumentAsset,
    titleArgument
  } from "../../mcp-apps/mcpApps";
  import McpAppFrames from "../../mcp-apps/McpAppFrames.svelte";
  import { getMcpAppPane } from "../../mcp-apps/McpAppPane.svelte";
  import ReasoningTrace from "./ReasoningTrace.svelte";
  import InternalToolStep from "./InternalToolStep.svelte";
  import ToolStepIcon from "./ToolStepIcon.svelte";
  import SkillActivationStep from "./SkillActivationStep.svelte";
  import { dynamicColour } from "$lib/core/colours";
  import { IconSpeechBubble } from "@eneo/icons/speech-bubble";
  import { formatEmojiTitle } from "$lib/core/formatting/formatEmojiTitle";
  import { getChatService } from "../../ChatService.svelte";
  import {
    capabilityProviderDetail,
    internalToolDoneLabel,
    isSkillActivation,
    serverDisplayName,
    toolDisplayName,
    toolStepIcon,
    toolStepKind,
    type ToolStepKind
  } from "../../internalToolLabels";
  import { getAttachmentUrlService } from "$lib/features/attachments/AttachmentUrlService.svelte";
  import { getMessageContext } from "../../MessageContext.svelte";
  import AsyncImage from "$lib/components/AsyncImage.svelte";
  import GeneratedFileChip from "./GeneratedFileChip.svelte";
  import { getFilePreview } from "$lib/features/file-preview/FilePreview.svelte";
  import { isDocument, revisedDocumentName, revisedFileId } from "../../documentVersions";
  import { m } from "$lib/paraglide/messages";
  import { ChevronRight, Check, X, Wrench } from "@lucide/svelte";
  import { SvelteMap, SvelteSet } from "svelte/reactivity";

  const chat = getChatService();
  const attachmentUrls = getAttachmentUrlService();
  const preview = getFilePreview();
  // Undefined where the conversation has no side panel; views then stay inline.
  const appPane = getMcpAppPane();

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
          purpose?: string | null;
          is_internal?: boolean | null;
          is_bundled?: boolean | null;
          generated_file_ids?: string[] | null;
          app_view?: unknown;
        }>
      | undefined
  );

  const documentAssetIds = $derived(
    new Set(
      (mcpToolCalls ?? [])
        .filter(isChartDocumentAsset)
        .flatMap((call) => chat.generatedFileIdsOf(call))
    )
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

  const conversationFiles = $derived.by(() => {
    const files = new SvelteMap<string, ToolInputFile>();
    for (const msg of chat.currentConversation?.messages ?? []) {
      for (const file of msg.files ?? [])
        files.set(file.id, { ...file, generated: files.get(file.id)?.generated ?? false });
      for (const file of msg.generated_files ?? [])
        files.set(file.id, { ...file, generated: true });
    }
    return files;
  });
  const readFileDetail = (tc: { arguments?: Record<string, unknown>; tool_call_id?: string }) => {
    const files = toolFileInputs(
      tc.arguments ?? chat.partialInputOf(tc.tool_call_id ?? ""),
      conversationFiles
    );
    return files.length
      ? files
          .map((file) =>
            file.generated
              ? m.tool_input_generated({ name: file.name })
              : m.tool_input_attached({ name: file.name })
          )
          .join(" · ")
      : null;
  };
  const previousAttempts = $derived(previousToolAttemptIndexes(tracedToolCalls, isStreamingTurn));
  const tracedSteps = $derived(
    tracedToolCalls.map((tc, i) => {
      const writing = chat.writingDocument;
      const denied =
        (!!tc.tool_call_id && deniedToolIds.has(tc.tool_call_id)) ||
        tc.approved === false ||
        tc.result_status === "denied" ||
        tc.result_status === "timeout_denied";
      const isLastTraced = i === tracedToolCalls.length - 1;
      const status = toolStepStatus(
        tc.result_status,
        denied,
        isStreamingTurn,
        toolsStillExecuting && isLastTraced
      );
      // The document the call created, if any: the step names it and opens it.
      const fileIds = chat.generatedFileIdsOf(tc);
      const file = message.generated_files.find(
        (candidate) => isDocument(candidate) && fileIds.includes(candidate.id)
      );
      const createsFile = tc.purpose === "file_creation";
      // The view of the call's result, once the panel can show it: the step
      // names it and opens it, as it does a document.
      const appCall = appViewCalls([tc])[0];
      const view =
        appCall && appPane?.offered.has(appCall.tool_call_id)
          ? {
              name: appViewSubject(appCall) ?? appViewTitle(appCall),
              open: () => appPane.open(appCall.tool_call_id)
            }
          : null;
      // A document being written is named as soon as its title has arrived.
      const writingTitle = createsFile
        ? ((tc.arguments?.title as string | undefined) ??
          chat.partialArgumentsOf(tc.tool_call_id)?.title)
        : undefined;
      // The document as far as it is written, so the step can show it again
      // after the reader closed the panel on it.
      const draft = createsFile && writing && writing.callId === tc.tool_call_id ? writing : null;
      // A change to an earlier document names that document while it is made.
      const updatingName = createsFile && !writingTitle ? revisedDocumentName(tc.arguments) : null;
      const activity = analysisStepLabels(
        analysisStep(tc, {
          ...chat.partialArgumentsOf(tc.tool_call_id),
          ...tc.arguments
        })
      );
      const toolName =
        activity?.running ??
        (writingTitle
          ? m.tool_document_writing({ name: writingTitle })
          : updatingName
            ? m.tool_document_updating({ name: updatingName })
            : toolDisplayName(
                tc.tool_name,
                tc.server_name,
                tc.title,
                tc.arguments,
                tc.purpose,
                tc.is_internal
              ));
      return {
        // The step opens the document at its newest version, a reader's
        // saved edit included.
        document: file
          ? {
              file: chat.documents.latestOf(file.id) ?? file,
              label: createsFile
                ? revisedFileId(tc.arguments)
                  ? (name: string) => m.tool_document_updated({ name })
                  : (name: string) => m.tool_document_created({ name })
                : (name: string) => m.tool_result_exported({ name })
            }
          : null,
        // Eneo's own tools and capability calls get localized labels; otherwise
        // prefer the server-provided title, falling back to the raw tool name.
        toolName,
        doneLabel:
          activity?.done ??
          internalToolDoneLabel(
            tc.tool_name,
            tc.server_name,
            tc.arguments,
            tc.purpose,
            tc.is_internal
          ) ??
          toolName,
        serverName: serverDisplayName(tc.server_name, tc.purpose, tc.is_internal),
        identity: `${tc.server_name} · ${tc.tool_name}`,
        // A result's title (a chart's, a table's) is the step's detail unless
        // the step already names it: as a view, or as a document being written.
        detail:
          readFileDetail(tc) ??
          (view || createsFile ? null : titleArgument(tc.arguments)) ??
          capabilityProviderDetail(tc),
        skillName: isSkillActivation(tc) ? (tc.title ?? tc.tool_name) : null,
        args: tc.arguments,
        toolCallId: tc.tool_call_id,
        status,
        previousAttempt: status === "failed" && !isSkillActivation(tc) && previousAttempts.has(i),
        // Function steps (capability calls, whichever provider served them)
        // and context steps (Eneo's own lookups) render as slim lines in runs
        // of their kind; general external servers keep their cards.
        kind: toolStepKind(tc),
        // A Skill activation sets up the work that follows: it belongs to
        // whichever slim run it sits in rather than to a kind of its own.
        neutral: isSkillActivation(tc),
        icon: toolStepIcon(tc.purpose),
        view,
        draft
      };
    })
  );
  // Built-in tools render as slim thinking-style lines in the message flow;
  // only external MCP calls keep their cards in the reasoning trace.
  // Contiguous steps of the same kind group into runs that render in call
  // order, so the trace stays chronological when a turn mixes kinds (e.g. a
  // knowledge search followed by a chart), and a lookup never folds into the
  // work that followed it.
  const stepRuns = $derived.by(() => {
    const runs: { kind: ToolStepKind; steps: typeof tracedSteps }[] = [];
    for (const step of tracedSteps) {
      const last = runs[runs.length - 1];
      // A neutral step joins the slim run around it, and a run of only
      // neutral steps takes the kind of the first step that follows them.
      const joins =
        last !== undefined &&
        last.kind !== "external" &&
        step.kind !== "external" &&
        (step.kind === last.kind || step.neutral || last.steps.every((s) => s.neutral));
      if (joins) {
        last.steps.push(step);
        if (!step.neutral) last.kind = step.kind;
      } else {
        runs.push({ kind: step.kind, steps: [step] });
      }
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
    run.steps.some(
      (step) => (step.status === "failed" && !step.previousAttempt) || step.status === "denied"
    );
  const runSummary = (steps: typeof tracedSteps) => {
    const servers = [...new Set(steps.map((step) => step.serverName))].join(" · ");
    return `${servers} · ${m.internal_tool_steps_count({ count: steps.length })}`;
  };
  // The functions a run used, in call order, shown as a cluster of their icons
  // before the summary; past this many the rest count as "+N".
  const MAX_RUN_ICONS = 3;
  const runIcons = (steps: typeof tracedSteps) => {
    const icons: NonNullable<(typeof tracedSteps)[number]["icon"]>[] = [];
    for (const step of steps) {
      if (step.icon && !icons.includes(step.icon)) icons.push(step.icon);
    }
    return icons;
  };
  // A step that created a document is that document's place in the chat, so
  // it never folds away with the others.
  const createdDocument = (step: (typeof tracedSteps)[number]) =>
    step.document !== null && step.status === "complete";
  // Documents no step of this answer accounts for (an answer saved before
  // calls recorded their files) keep a card, so each stays reachable. A
  // version a reader saved belongs to the document it revises, which the
  // step that made the document opens at its newest version.
  const unclaimedDocumentIds = $derived.by(() => {
    const claimed = new Set(
      tracedSteps.flatMap((step) =>
        step.kind !== "external" && step.document
          ? [
              step.document.file.id,
              ...chat.documents.versionsOf(step.document.file.id).map((version) => version.id)
            ]
          : []
      )
    );
    return new Set(
      message.generated_files
        .filter((file) => isDocument(file) && !claimed.has(file.id) && !file.revises_file_id)
        .map((file) => file.id)
    );
  });

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

  // The names an answer can mention a document by: each is a link to it.
  const documentNames = $derived([
    ...new Set(
      chat.documents.documents.flatMap((document) =>
        document.versions.map((version) => version.name)
      )
    )
  ]);

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
  {#if reasoningText.trim().length > 0 && (stepRuns.length === 0 || stepRuns[0].kind !== "external")}
    <div class="mb-4">
      <ReasoningTrace reasoning={reasoningText} working={toolsStillExecuting} />
    </div>
  {/if}

  {#each stepRuns as run, runIndex (runIndex)}
    {#if run.kind === "external"}
      <div class="mb-4">
        <ReasoningTrace
          steps={run.steps}
          reasoning={runIndex === 0 ? reasoningText : ""}
          working={toolsStillExecuting && runIndex === stepRuns.length - 1}
          loadToolResult={(toolCallId) => chat.getToolCallResult(toolCallId)}
        />
      </div>
    {:else}
      <!-- The same keyed {#each} renders the run whether it is still working
           (latest step only) or done (every step), so a step opened mid-run
           keeps its panel open when the result lands. -->
      {@const working = runWorking(run, runIndex)}
      {@const foldable = run.steps.filter((step) => !createdDocument(step))}
      {@const folded = !working && foldable.length > 1}
      {@const visibleSteps = working ? run.steps.slice(-1) : run.steps}
      <!-- Function rows carry a chip taller than their text, so they get more air than rows of plain text. -->
      {@const rowGap = run.kind === "function" ? "gap-1.5" : "gap-0.5"}
      <div class="mb-4 flex flex-col {rowGap}">
        {#if folded}
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
            {#if run.kind === "function"}
              {@const icons = runIcons(run.steps)}
              <!-- The summary text names the functions; the cluster only shows them. -->
              <span class="flex shrink-0 items-center gap-1" aria-hidden="true">
                {#each icons.slice(0, MAX_RUN_ICONS) as icon, i (i)}
                  <ToolStepIcon {icon} />
                {/each}
                {#if icons.length > MAX_RUN_ICONS}
                  <span
                    class="bg-secondary text-muted flex size-5 items-center justify-center rounded-md text-[10px] font-medium"
                  >
                    +{icons.length - MAX_RUN_ICONS}
                  </span>
                {/if}
              </span>
            {/if}
            {#if runFailed(run)}
              <X class="text-negative-default h-3.5 w-3.5 shrink-0" />
            {/if}
            <span class="truncate font-medium">{runSummary(run.steps)}</span>
          </button>
        {/if}
        {#if !folded || openInternalRuns.has(runIndex)}
          <div class="flex flex-col {rowGap} {folded ? 'pl-7' : ''}">
            {#each visibleSteps as step, i (step.toolCallId ?? i)}
              {#if step.skillName !== null}
                <SkillActivationStep
                  name={step.skillName}
                  live={isStreamingTurn}
                  args={step.args}
                  status={step.status}
                />
              {:else}
                <InternalToolStep
                  runningLabel={step.toolName}
                  doneLabel={step.doneLabel}
                  serverName={step.serverName}
                  identity={step.identity}
                  detail={step.detail}
                  args={step.args}
                  toolCallId={step.toolCallId}
                  status={step.status}
                  previousAttempt={step.previousAttempt}
                  document={step.document}
                  icon={step.icon}
                  view={step.view}
                  draft={step.draft}
                  onLoadResult={step.toolCallId
                    ? () => chat.getToolCallResult(step.toolCallId!)
                    : undefined}
                />
              {/if}
            {/each}
          </div>
        {/if}
        {#if folded && !openInternalRuns.has(runIndex)}
          {#each run.steps.filter(createdDocument) as step, i (step.toolCallId ?? i)}
            <InternalToolStep
              runningLabel={step.toolName}
              doneLabel={step.doneLabel}
              serverName={step.serverName}
              identity={step.identity}
              status={step.status}
              document={step.document}
              detail={step.detail}
              icon={step.icon}
            />
          {/each}
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
                  >{toolDisplayName(
                    toolCall.tool_name,
                    toolCall.server_name,
                    toolCall.title,
                    undefined,
                    toolCall.purpose,
                    toolCall.is_internal
                  )}</span
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
              <span class="text-muted text-xs"
                >{serverDisplayName(
                  toolCall.server_name,
                  toolCall.purpose,
                  toolCall.is_internal
                )}</span
              >
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
    fileNames={documentNames}
    customRenderers={{
      inref: MessageEneoInfoBlob,
      file: MessageDocumentLink
    }}
  />
</div>

<McpImageAttachments />

<McpAppFrames />

{#each message.generated_files.filter((file) => !documentAssetIds.has(file.id)) as file (file.id)}
  <!-- An empty mimetype is the placeholder of an image still being generated. -->
  {#if !file.mimetype || file.mimetype.startsWith("image/")}
    <AsyncImage url={attachmentUrls.getUrl(file) ?? null}></AsyncImage>
  {:else if !preview || unclaimedDocumentIds.has(file.id)}
    <!-- A document is opened from the step that created it. It gets a card
         only where no step shows it, or where there is no panel to open it in.
         Documents download their exact bytes, never the extracted text. -->
    <GeneratedFileChip {file} url={attachmentUrls.getOriginalUrl(file) ?? null} />
  {/if}
{/each}
