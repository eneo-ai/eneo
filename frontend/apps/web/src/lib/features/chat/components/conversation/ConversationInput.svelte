<script lang="ts">
  import { tableLocationLabel } from "$lib/features/file-preview/tableReference";
  import { untrack } from "svelte";
  import AttachmentUploadIconButton from "$lib/features/attachments/components/AttachmentUploadIconButton.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as PromptInput from "$lib/components/ai-elements/prompt-input/index.js";
  import {
    getAttachmentManager,
    UploadsNotReadyError
  } from "$lib/features/attachments/AttachmentManager";
  import { derived } from "svelte/store";
  import MentionInput from "../mentions/MentionInput.svelte";
  import { initMentionInput } from "../mentions/MentionInput";
  import MentionButton from "../mentions/MentionButton.svelte";
  import ChatModelSelect from "../switcher/ChatModelSelect.svelte";
  import ChatReasoningSelect from "../switcher/ChatReasoningSelect.svelte";
  import ChatKnowledge from "./ChatKnowledge.svelte";
  import ChatMcpServers from "./ChatMcpServers.svelte";
  import ChatSkills from "./ChatSkills.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getChatService } from "../../ChatService.svelte";
  import { effectiveKnowledgeMode, internalMcpServerNames } from "../../internalMcpAvailability";
  import { track } from "$lib/core/helpers/track";
  import { getAppContext } from "$lib/core/AppContext";
  import { m } from "$lib/paraglide/messages";
  import { SvelteSet } from "svelte/reactivity";
  import TextQuote from "@lucide/svelte/icons/text-quote";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import X from "@lucide/svelte/icons/x";
  import { getErrorMessage } from "$lib/core/errors/getErrorMessage";
  import { getCapability, canUseCapability } from "$lib/features/mcp/capabilities";
  import { getPartnerKnowledgeSources, hasKnowledgeSources } from "../../knowledgeSources";
  import { getContextErrorInfo, isConversationSubmitDisabled } from "./conversationInputState";
  import { getFilePreview } from "$lib/features/file-preview/FilePreview.svelte";
  import { getMcpAppPane } from "../../mcp-apps/McpAppPane.svelte";
  import { composeQuotedQuestion, tableQuoteSummary } from "../../questionQuote";

  const chat = getChatService();
  const { user } = getAppContext();

  const {
    state: { attachments, uploadError },
    queueValidUploads,
    clearUploadError,
    removeUploads,
    awaitUploads
  } = getAttachmentManager();

  const {
    states: { mentions, question },
    resetMentionInput,
    setQuestionText,
    snapshotMentionInput,
    restoreMentionInput,
    isMentionInputEmpty,
    focusMentionInput
  } = initMentionInput({
    triggerCharacter: "@",
    tools: () => chat.partner.tools,
    onEnterPressed: ask
  });

  type Props = { scrollToBottom: () => void; onNewConversation?: () => void };

  const { scrollToBottom, onNewConversation }: Props = $props();

  // An interactive tool view may offer the reader a message. It is put after
  // whatever is already written and is never sent by itself.
  $effect(() => {
    const suggestion = chat.composerSuggestion;
    if (suggestion === null) return;
    untrack(() => {
      chat.composerSuggestion = null;
      setQuestionText($question ? `${$question}\n${suggestion}` : suggestion);
      focusMentionInput();
    });
  });

  // Text the user selected in a file preview or an interactive view; it is
  // sent as a quote at the head of the next question.
  const filePreview = getFilePreview();
  const appPane = getMcpAppPane();
  const quote = $derived(filePreview?.quote ?? null);
  // A quoted view is shown again beside the conversation when it can be.
  const quotedView = $derived(
    quote?.viewCallId && appPane?.offered.has(quote.viewCallId) ? quote.viewCallId : null
  );
  const quotedFile = $derived(
    chat.currentConversation.messages
      ?.flatMap((message) => [...(message.files ?? []), ...(message.generated_files ?? [])])
      .find((file) => file.id === quote?.fileId)
  );

  // Quoting is followed by typing what to do with the passage.
  $effect(() => {
    if (quote) focusMentionInput();
  });

  let abortController: AbortController | undefined;
  const autoAcceptTools = $derived(!chat.settings?.require_tool_approval);
  const settingsDisabled = $derived(
    !chat.settings ||
      chat.settingsBusy ||
      chat.askQuestion.isLoading ||
      chat.settingsResolution?.settings_compatible === false
  );

  $effect(() => {
    const conversation = chat.currentConversation;
    untrack(() => {
      if (conversation) void chat.loadSettings();
    });
  });

  function persistMcpServerSelection(disabledServerIds: ReadonlySet<string>) {
    const mcp_server_states = { ...chat.settings?.mcp_server_states };
    const capability_states = { ...chat.settings?.capability_states };
    for (const id of availableMcpServerIds) {
      const purpose = getCapability(
        id.startsWith("capability:") ? id.slice("capability:".length) : null
      )?.purpose;
      if (purpose) capability_states[purpose] = !disabledServerIds.has(id);
      else mcp_server_states[id] = !disabledServerIds.has(id);
    }
    void chat.updateSettings({ mcp_server_states, capability_states });
  }

  function queueUploadsFromClipboard(event: ClipboardEvent) {
    if (!event.clipboardData?.files || event.clipboardData.files.length === 0) return;
    // A message in flight owns the attachment list; files pasted now would be
    // dropped with the sent batch.
    if (chat.askQuestion.isLoading || sendPending) return;
    // Validation errors surface inline via the manager's uploadError store.
    queueValidUploads([...event.clipboardData.files]);
  }

  let inputError = $state<{ message: string; details?: string; isContextError?: boolean } | null>(
    null
  );
  let errorInputSnapshot = { question: "", attachmentIds: "" };

  const startNewConversation = () => {
    inputError = null;
    clearUploadError();
    errorInputSnapshot = { question: "", attachmentIds: "" };
    if (onNewConversation) onNewConversation();
    else chat.newConversation();
  };

  // Set synchronously on send and held until the conversation request has
  // settled, so Enter or Send during the wait for a queued model switch (or
  // the draft restore after a failure) cannot start an overlapping request.
  let sendPending = $state(false);

  async function ask() {
    if (isAskingDisabled) return;
    sendPending = true;
    inputError = null;
    // The controller is kept locally too: by the time the catch below runs a
    // later send may have replaced the shared one.
    const controller = new AbortController();
    abortController = controller;
    // Attachments still uploading do not hold the message back. It leaves the
    // composer at once and waits in the conversation, mirroring their
    // progress, until all of them are on the server.
    const sentIds = $attachments.map((attachment) => attachment.id);
    const allUploaded = $attachments.every(
      (attachment) => attachment.status === "completed" && attachment.fileRef
    );
    const files = allUploaded
      ? $attachments.map((attachment) => attachment.fileRef).filter((file) => file !== undefined)
      : {
          ids: sentIds,
          subscribe: derived(attachments, (list) =>
            list.filter((attachment) => sentIds.includes(attachment.id))
          ).subscribe,
          ready: () => awaitUploads(sentIds, controller.signal)
        };
    const tools =
      $mentions.length > 0
        ? {
            assistants: $mentions.map((mention) => {
              return { id: mention.id, handle: mention.handle };
            })
          }
        : undefined;
    // Approval controls external MCP servers only. Eneo's read-only internal
    // knowledge/files tools are core capabilities and always auto-execute.
    // The question is echoed in the conversation as soon as the backend
    // confirms it, so clear the composer now instead of showing it dimmed
    // behind a spinner until the answer finishes. The full draft (mention
    // chips included) is restored on error below.
    const draft = snapshotMentionInput();
    const sentQuote = quote;
    const questionText = composeQuotedQuestion(sentQuote, draft.question);
    resetMentionInput();
    if (filePreview) filePreview.quote = null;
    scrollToBottom();

    try {
      // A Skills change is saved on the default assistant; the backend answers
      // with what is stored, so let that write land before the question is sent.
      await spacesManager?.awaitDefaultAssistantUpdates();
      await chat.askQuestion(questionText, files, tools, undefined, controller);
      removeUploads(sentIds);
    } catch (error: unknown) {
      // Put the draft back unless the user has already started a new one
      // while the request was pending; that newer input wins.
      if (isMentionInputEmpty()) restoreMentionInput(draft);
      if (filePreview && !filePreview.quote) filePreview.quote = sentQuote;
      // A cancelled send is not an error, and a failed upload has already
      // been reported by the attachment manager next to its list.
      if (controller.signal.aborted || error instanceof UploadsNotReadyError) return;
      const contextError = getContextErrorInfo(error);
      if (contextError) {
        if (contextError.used !== undefined && contextError.limit !== undefined) {
          const excess = contextError.used - contextError.limit;
          inputError = {
            message: m.context_window_exceeded(),
            details: `${contextError.used.toLocaleString()} / ${contextError.limit.toLocaleString()} tokens (${excess.toLocaleString()} ${m.over()}). ${m.context_window_input_preserved()}`,
            isContextError: true
          };
        } else {
          inputError = {
            message: m.context_window_exceeded(),
            details: m.context_window_input_preserved(),
            isContextError: true
          };
        }
      } else {
        inputError = { message: getErrorMessage(error) };
      }
      errorInputSnapshot = {
        question: $question,
        attachmentIds: $attachments
          .map((a) => a.fileRef?.id ?? "")
          .sort()
          .join(",")
      };
      focusMentionInput();
    } finally {
      sendPending = false;
    }
  }

  // Clear error when user changes input (text or attachments)
  $effect(() => {
    const q = $question;
    const currentIds = $attachments
      .map((a) => a.fileRef?.id ?? "")
      .sort()
      .join(",");
    const snap = errorInputSnapshot;
    if (snap.question && (q !== snap.question || currentIds !== snap.attachmentIds)) {
      inputError = null;
      errorInputSnapshot = { question: "", attachmentIds: "" };
    }
  });

  $effect(() => {
    track(chat.partner, chat.currentConversation);
    focusMentionInput();
  });

  // Request a token preflight whenever the user input or attached files
  // change. Debounced inside ChatService; safe to fire on every keystroke.
  $effect(() => {
    // Recalculate for the model that will answer the next turn.
    track(chat.partner, chat.selectedPersonalModel, chat.settings, chat.settingsBusy);
    const fileIds = $attachments
      .map((a) => a.fileRef?.id)
      .filter((id): id is string => Boolean(id));
    const tools =
      $mentions.length > 0
        ? {
            assistants: $mentions.map((mention) => {
              return { id: mention.id, handle: mention.handle };
            })
          }
        : undefined;
    chat.requestPreflight(composeQuotedQuestion(quote, $question), fileIds, tools);
  });

  const shouldShowMentionButton = $derived.by(() => {
    const hasTools = chat.partner.tools.assistants.length > 0;
    const isEnabled =
      chat.partner.type === "default-assistant" ||
      ("allow_mentions" in chat.partner && chat.partner.allow_mentions);
    return hasTools && isEnabled;
  });

  const supportsToolCalling = $derived(chat.settingsResolution?.supports_tool_calling ?? false);
  const generalMcpServers = $derived(
    (chat.settingsResolution?.mcp_servers ?? []).map((server) => ({
      ...server,
      reason: server.reason ?? null
    }))
  );
  const capabilityServers = $derived(
    (chat.settingsResolution?.capabilities ?? [])
      .filter((capability) => canUseCapability(user, capability.purpose))
      .map((capability) => ({
        ...capability,
        id: `capability:${capability.purpose}`,
        name: capability.purpose,
        reason: capability.reason ?? null
      }))
  );
  const availableMcpServerIds = $derived(
    [...generalMcpServers, ...capabilityServers].map((s) => s.id)
  );

  const disabledMcpServerIds = $derived.by(() => {
    const disabled = new SvelteSet<string>();
    for (const tool of [...generalMcpServers, ...capabilityServers]) {
      if (!tool.selected) disabled.add(tool.id);
    }
    return disabled;
  });

  // Whether the popover has anything to show: general servers plus the
  // capabilities this user may use (a capability the role withholds is not a
  // row, so it must not open an empty popover either).
  const hasMcpTools = $derived(generalMcpServers.length + capabilityServers.length > 0);

  // Knowledge sources attached to the partner (read-only indicator; knowledge
  // cannot be toggled per conversation the way MCP servers can).
  const knowledgeSources = $derived(getPartnerKnowledgeSources(chat.partner));
  const hasKnowledge = $derived(hasKnowledgeSources(knowledgeSources));
  const partnerKnowledgeMode = $derived.by(() => {
    const partner = chat.partner as Record<string, unknown> | null;
    return typeof partner?.knowledge_mode === "string" ? partner.knowledge_mode : undefined;
  });

  const runtimeKnowledgeMode = $derived(
    effectiveKnowledgeMode(partnerKnowledgeMode, supportsToolCalling)
  );

  // Files the backend's files server considers: current uploads, persisted
  // user-message attachments, and the assistant's own attachments marked
  // "open with tool" (inline_text false). Inlined assistant attachments never
  // get a reference URL and so do not activate the tool.
  const hasDownloadReference = $derived.by(() => {
    const pending = $attachments
      .map((attachment) => attachment.fileRef)
      .filter((file) => file !== undefined);
    const history = (chat.currentConversation?.messages ?? []).flatMap(
      (message) => message.files ?? []
    );
    // Group chats type their (always empty) attachments without a mode.
    const toolAttachments = (chat.partner?.attachments ?? []).filter(
      (file) => "inline_text" in file && file.inline_text === false
    );
    return [...pending, ...history, ...toolAttachments].some(
      (file) => file.has_download_reference === true
    );
  });

  // Eneo's built-in loopback MCP servers that will be active for this partner:
  // always on, not togglable, but surfaced next to the external servers so the
  // user sees every tool the model can reach. Mirrors the backend attach gates
  // (knowledge_mode "tool" + knowledge attached; some file reaching the model
  // as a signed URL read by the files server).
  const internalMcpServers = $derived.by(() => {
    return internalMcpServerNames({
      supportsToolCalling,
      hasKnowledge,
      storedKnowledgeMode: partnerKnowledgeMode,
      hasDownloadReference
    }).map((name) => ({ name }));
  });

  // The picker uses SpacesManager for the available model catalog. Other
  // mounts of the default assistant (e.g. a deep link into dashboard chat)
  // have no such context, so gate on its presence or the picker throws on init.
  const spacesManager = getSpacesManager();
  const showModelSelect = $derived(
    chat.partner.type === "default-assistant" && Boolean(spacesManager)
  );

  // Preflight is advisory. Keep Send enabled when only the estimate exceeds
  // the context window and let the provider validate the final payload.
  const isAskingDisabled = $derived(
    isConversationSubmitDisabled({
      isLoading: chat.askQuestion.isLoading,
      sendPending:
        sendPending ||
        settingsDisabled ||
        Boolean(chat.settingsError) ||
        Boolean(chat.settingsResolution?.model_unavailable),
      hasContent: $question !== "" || $attachments.length > 0,
      hasCompletionModel: chat.hasCompletionModel,
      estimatedExceedsContext: chat.willExceedContext
    })
  );
</script>

<PromptInput.Root
  status={chat.askQuestion.isLoading || sendPending ? "streaming" : "ready"}
  onSubmit={ask}
  onStop={() => abortController?.abort("User cancelled")}
  class="min-w-0"
>
  {#if quote && filePreview}
    {@const location = tableLocationLabel(quote.locator, (row) => m.table_reference_row({ row }))}
    <!-- A quotation, not a disabled surface: the accent tint and rule mark it as part of
         what is about to be sent. -->
    <div
      class="bg-accent-dimmer border-accent-default mx-1.5 mt-1.5 flex items-start gap-2.5 rounded-lg border-l-[3px] py-2 pr-2 pl-3"
    >
      <TextQuote class="text-accent-stronger mt-0.5 size-4 flex-shrink-0" aria-hidden="true" />
      <button
        type="button"
        class="focus-visible:ring-ring min-w-0 flex-1 rounded text-left focus-visible:ring-2 focus-visible:outline-none"
        disabled={!quotedFile && !quotedView}
        aria-label={m.file_quote_show({ name: quote.fileName })}
        onclick={(event) => {
          if (quotedView) appPane?.open(quotedView);
          else if (quotedFile) filePreview.showPassage(quotedFile, quote, event.currentTarget);
        }}
      >
        <span class="text-accent-stronger block truncate text-xs font-medium"
          >{m.file_quote_from({ name: quote.fileName })}</span
        >
        {#if location}<span class="text-secondary block text-xs">{location}</span>{/if}
        {#if tableQuoteSummary(quote.text)}
          {@const table = tableQuoteSummary(quote.text)!}
          <!-- No room for the table itself here: its columns and size stand in. -->
          <span class="text-default block truncate text-sm">{table.columns.join(" · ")}</span>
          <span class="text-secondary block text-xs">
            {table.rows === 1
              ? m.file_quote_table_row()
              : m.file_quote_table_rows({ count: table.rows })}
          </span>
        {:else}
          <span class="text-default line-clamp-2 text-sm break-words whitespace-pre-line"
            >{quote.text}</span
          >
        {/if}
        {#if quote.fileId && !quotedFile}<span class="text-secondary block text-xs"
            >{m.table_reference_unavailable()}</span
          >{/if}
      </button>
      <button
        type="button"
        onclick={() => (filePreview.quote = null)}
        class="text-secondary hover:bg-background hover:text-default focus-visible:ring-ring rounded p-0.5 transition-colors focus-visible:ring-2 focus-visible:outline-none"
        aria-label={m.file_quote_remove()}
      >
        <X class="size-4" />
      </button>
    </div>
  {/if}

  <PromptInput.Body>
    {#if !chat.hasCompletionModel}
      <!-- Cover only the text field: the footer stays usable so the user can
           pick a model themselves whenever the selector has one to offer. -->
      <div
        class="bg-card/80 absolute inset-0 z-10 flex items-center justify-center rounded-t-2xl backdrop-blur-[1px]"
      >
        <div class="text-muted-foreground flex items-center gap-2 px-4 text-sm">
          <TriangleAlert class="h-4 w-4 flex-shrink-0" />
          <p>{m.no_completion_model_description()}</p>
        </div>
      </div>
    {/if}
    <MentionInput onpaste={queueUploadsFromClipboard}></MentionInput>
  </PromptInput.Body>

  {#if chat.settingsError || chat.settingsResolution?.settings_compatible === false || chat.settingsResolution?.model_unavailable}
    <div class="text-destructive flex items-center gap-2 px-3 py-2 text-sm" role="alert">
      <p>
        {#if chat.settingsError}
          {m.conversation_settings_save_failed()} {getErrorMessage(chat.settingsError)}
        {:else if chat.settingsResolution?.settings_compatible === false}
          {m.conversation_settings_incompatible()}
        {:else}
          {m.conversation_settings_model_unavailable()}
        {/if}
      </p>
      <Button
        variant="ghost"
        size="sm"
        disabled={chat.settingsBusy || chat.askQuestion.isLoading}
        onclick={() => void chat.loadSettings(true)}>{m.conversation_settings_reload()}</Button
      >
    </div>
  {/if}

  {#if $uploadError}
    <div
      class="text-destructive bg-destructive/10 mx-1.5 mt-1 flex items-start justify-between gap-2 rounded-md px-2 py-1.5 text-sm"
      role="alert"
    >
      <div class="flex items-start gap-2">
        <TriangleAlert class="mt-0.5 h-4 w-4 flex-shrink-0" />
        <p class="whitespace-pre-line">{$uploadError}</p>
      </div>
      <button
        type="button"
        onclick={clearUploadError}
        class="hover:bg-destructive/10 -mr-0.5 rounded p-0.5"
        aria-label={m.dismiss()}
      >
        <X class="h-4 w-4" />
      </button>
    </div>
  {/if}

  {#if inputError}
    <div
      class="text-destructive bg-destructive/10 mx-1.5 mt-1 flex items-start justify-between gap-2 rounded-md px-2 py-1.5 text-sm"
      role="alert"
    >
      <div class="flex items-start gap-2">
        <TriangleAlert class="mt-0.5 h-4 w-4 flex-shrink-0" />
        <div>
          <p class="font-medium">{inputError.message}</p>
          {#if inputError.details}
            <p class="mt-0.5">{inputError.details}</p>
          {/if}
        </div>
      </div>
      {#if inputError.isContextError}
        <Button
          variant="outline"
          size="sm"
          type="button"
          onclick={startNewConversation}
          class="ml-2 h-7 flex-shrink-0 self-center whitespace-nowrap"
        >
          {m.new_conversation()}
        </Button>
      {/if}
    </div>
  {/if}

  <PromptInput.Footer class="flex-wrap gap-1 px-1.5 @[36rem]/composer:gap-2 @[36rem]/composer:px-2">
    <PromptInput.Tools
      class={[
        "shrink-0 gap-0.5 @[36rem]/composer:gap-1",
        chat.askQuestion.isLoading && "pointer-events-none opacity-40"
      ]}
    >
      <AttachmentUploadIconButton label={m.upload_documents_to_conversation()} />
      {#if shouldShowMentionButton}
        <MentionButton></MentionButton>
      {/if}

      {#if hasKnowledge}
        <ChatKnowledge
          collections={knowledgeSources.collections}
          websites={knowledgeSources.websites}
          integrations={knowledgeSources.integrations}
          knowledgeMode={runtimeKnowledgeMode}
        />
      {/if}

      {#if hasMcpTools || internalMcpServers.length > 0}
        <ChatMcpServers
          servers={generalMcpServers}
          {capabilityServers}
          internalServers={internalMcpServers}
          modelSupportsTools={supportsToolCalling}
          disabledServerIds={disabledMcpServerIds}
          onSelectionChange={persistMcpServerSelection}
          {autoAcceptTools}
          disabled={settingsDisabled}
          showApproval={chat.partner.type !== "group-chat"}
          onAutoAcceptChange={(enabled) =>
            void chat.updateSettings({ require_tool_approval: !enabled })}
        />
      {/if}

      {#if showModelSelect}
        <!-- Saves to the default assistant through the same SpacesManager as the model picker. -->
        <ChatSkills />
      {/if}
    </PromptInput.Tools>

    <!-- Right cluster: model + send/stop -->
    <div
      class="flex min-w-[7rem] flex-1 items-center justify-end gap-0.5 @[26rem]/composer:min-w-0 @[36rem]/composer:gap-2"
    >
      {#if showModelSelect}
        <ChatModelSelect onNewConversation={startNewConversation} />
        <ChatReasoningSelect />
      {/if}

      <PromptInput.Submit class="shrink-0" disabled={isAskingDisabled} name="ask" />
    </div>
  </PromptInput.Footer>
</PromptInput.Root>
