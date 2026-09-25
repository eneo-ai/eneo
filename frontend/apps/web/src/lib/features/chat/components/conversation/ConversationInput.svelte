<script lang="ts">
  import { untrack } from "svelte";
  import AttachmentUploadIconButton from "$lib/features/attachments/components/AttachmentUploadIconButton.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as PromptInput from "$lib/components/ai-elements/prompt-input/index.js";
  import { getAttachmentManager } from "$lib/features/attachments/AttachmentManager";
  import MentionInput from "../mentions/MentionInput.svelte";
  import { initMentionInput } from "../mentions/MentionInput";
  import MentionButton from "../mentions/MentionButton.svelte";
  import ChatModelSelect from "../switcher/ChatModelSelect.svelte";
  import ChatReasoningSelect from "../switcher/ChatReasoningSelect.svelte";
  import ChatKnowledge from "./ChatKnowledge.svelte";
  import ChatMcpServers from "./ChatMcpServers.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getChatService } from "../../ChatService.svelte";
  import { effectiveKnowledgeMode, internalMcpServerNames } from "../../internalMcpAvailability";
  import { selectEffectiveChatModel } from "../../selectEffectiveChatModel";
  import { track } from "$lib/core/helpers/track";
  import { getAppContext } from "$lib/core/AppContext";
  import { m } from "$lib/paraglide/messages";
  import { SvelteSet } from "svelte/reactivity";
  import { TriangleAlert, X } from "@lucide/svelte";
  import { getErrorMessage } from "$lib/core/errors/getErrorMessage";
  import { getCapability, isCapabilityPurpose } from "$lib/features/mcp/capabilities";
  import { chatCapabilities } from "../../chatCapabilities";
  import { getContextErrorInfo, isConversationSubmitDisabled } from "./conversationInputState";

  type McpServerSummary = {
    id: string;
    name: string;
    description?: string | null;
    icon_url?: string | null;
    /** "general" for ordinary MCP servers, otherwise a capability purpose (web search, image generation). */
    purpose?: string | null;
    /** Org-level availability: a deactivated server stays attached but is never called. */
    is_enabled?: boolean;
    readiness_reason?: string | null;
  };

  const chat = getChatService();
  const { user } = getAppContext();

  const {
    state: { attachments, isUploading, uploadError },
    queueValidUploads,
    clearUploads,
    clearUploadError
  } = getAttachmentManager();

  const {
    states: { mentions, question },
    resetMentionInput,
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

  let abortController: AbortController | undefined;
  const autoAcceptTools = $derived(!chat.settings?.require_tool_approval);
  const settingsDisabled = $derived(
    !chat.settings || chat.settingsBusy || chat.askQuestion.isLoading
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
    const files = $attachments.map((file) => file?.fileRef).filter((file) => file !== undefined);
    abortController = new AbortController();
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
    const questionText = draft.question;
    resetMentionInput();
    scrollToBottom();

    try {
      await chat.askQuestion(questionText, files, tools, undefined, abortController);
      clearUploads();
    } catch (error: unknown) {
      // Put the draft back unless the user has already started a new one
      // while the request was pending; that newer input wins.
      if (isMentionInputEmpty()) restoreMentionInput(draft);
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
    chat.requestPreflight($question, fileIds, tools);
  });

  const shouldShowMentionButton = $derived.by(() => {
    const hasTools = chat.partner.tools.assistants.length > 0;
    const isEnabled =
      chat.partner.type === "default-assistant" ||
      ("allow_mentions" in chat.partner && chat.partner.allow_mentions);
    return hasTools && isEnabled;
  });

  // MCP servers available to the current partner (drives the toolbar popover).
  // For the personal/default assistant the policy GRANTS servers that are not
  // attached to the entity itself, so read them from effective_config (mirrors
  // the backend); otherwise fall back to the assistant's own mcp_servers.
  const mcpServers = $derived.by(() => {
    const partner = chat.partner;
    if (!partner) return [];
    if ("effective_config" in partner && partner.effective_config?.mcp_enforced) {
      return (partner.effective_config.available_mcp_servers ?? []) as Array<McpServerSummary>;
    }
    if ("mcp_servers" in partner && Array.isArray(partner.mcp_servers)) {
      return partner.mcp_servers as Array<McpServerSummary>;
    }
    return [];
  });

  // The tenant's capability providers (web search, image generation) flow
  // through the same MCP inheritance chain as other servers but are presented
  // as capabilities, not servers: split them out of the generic rows and give
  // each its own popover entry. A capability the user's role may not use is
  // hidden; the backend never attaches its tools for that user anyway.
  const generalMcpServers = $derived(
    mcpServers
      .filter((server) => !isCapabilityPurpose(server.purpose))
      .map((server) => ({
        ...server,
        available: server.is_enabled !== false,
        reason: server.is_enabled === false ? "server_disabled" : null
      }))
  );
  const capabilityServers = $derived(chatCapabilities(chat.partner, user));
  const availableMcpServerIds = $derived(
    [...generalMcpServers, ...capabilityServers].map((s) => s.id)
  );

  const disabledMcpServerIds = $derived.by(() => {
    const disabled = new SvelteSet<string>();
    const config = "effective_config" in chat.partner ? chat.partner.effective_config : null;
    for (const id of availableMcpServerIds) {
      const purpose = getCapability(
        id.startsWith("capability:") ? id.slice("capability:".length) : null
      )?.purpose;
      const enabled = purpose
        ? (chat.settings?.capability_states?.[purpose] ??
          !config?.default_disabled_capabilities?.includes(purpose))
        : (chat.settings?.mcp_server_states?.[id] ??
          !config?.default_disabled_mcp_server_ids?.includes(id));
      if (!enabled) disabled.add(id);
    }
    return disabled;
  });

  // Whether the popover has anything to show: general servers plus the
  // capabilities this user may use (a capability the role withholds is not a
  // row, so it must not open an empty popover either).
  const hasMcpTools = $derived(generalMcpServers.length + capabilityServers.length > 0);

  // Knowledge sources attached to the partner (read-only indicator; knowledge
  // cannot be toggled per conversation the way MCP servers can).
  type NamedSource = { id: string; name: string };
  const knowledgeSources = $derived.by(() => {
    const partner = chat.partner as Record<string, unknown> | null;
    const named = (value: unknown, fallbackKey?: string): NamedSource[] =>
      Array.isArray(value)
        ? value.map((source) => ({
            id: String(source.id),
            name: String(source.name ?? (fallbackKey ? (source[fallbackKey] ?? "") : ""))
          }))
        : [];
    return {
      collections: named(partner?.groups),
      websites: named(partner?.websites, "url"),
      integrations: named(partner?.integration_knowledge_list)
    };
  });
  const hasKnowledge = $derived(
    knowledgeSources.collections.length +
      knowledgeSources.websites.length +
      knowledgeSources.integrations.length >
      0
  );
  const partnerKnowledgeMode = $derived.by(() => {
    const partner = chat.partner as Record<string, unknown> | null;
    return typeof partner?.knowledge_mode === "string" ? partner.knowledge_mode : undefined;
  });

  const effectiveModel = $derived.by(() => {
    const partner = chat.partner;
    if (!partner || !("completion_model" in partner)) return undefined;
    return partner.type === "default-assistant" && chat.selectedPersonalModel
      ? chat.selectedPersonalModel
      : selectEffectiveChatModel(partner.completion_model, partner.effective_config);
  });
  const supportsToolCalling = $derived(effectiveModel?.supports_tool_calling === true);
  const runtimeKnowledgeMode = $derived(
    effectiveKnowledgeMode(partnerKnowledgeMode, supportsToolCalling)
  );

  // Current uploads and persisted user-message attachments are the only files
  // the backend's files server considers. Assistant prompt attachments remain
  // inline and therefore do not activate this tool.
  const hasDownloadReference = $derived.by(() => {
    const pending = $attachments
      .map((attachment) => attachment.fileRef)
      .filter((file) => file !== undefined);
    const history = (chat.currentConversation?.messages ?? []).flatMap(
      (message) => message.files ?? []
    );
    return [...pending, ...history].some((file) => file.has_download_reference === true);
  });

  // Eneo's built-in loopback MCP servers that will be active for this partner:
  // always on, not togglable, but surfaced next to the external servers so the
  // user sees every tool the model can reach. Mirrors the backend attach gates
  // (knowledge_mode "tool" + knowledge attached; inline_file_text off means
  // attachments reach the model as signed URLs read by the files server).
  const internalMcpServers = $derived.by(() => {
    const partner = chat.partner as Record<string, unknown> | null;
    return internalMcpServerNames({
      supportsToolCalling,
      hasKnowledge,
      storedKnowledgeMode: partnerKnowledgeMode,
      inlineFileText: partner?.inline_file_text !== false,
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
      sendPending: sendPending || settingsDisabled || Boolean(chat.settingsError),
      isUploading: $isUploading,
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
  class="max-w-[74ch] md:w-full"
>
  {#if !chat.hasCompletionModel}
    <div
      class="bg-card/80 absolute inset-0 z-10 flex items-center justify-center rounded-2xl backdrop-blur-[1px]"
    >
      <div class="text-muted-foreground flex items-center gap-2 px-4 text-sm">
        <TriangleAlert class="h-4 w-4 flex-shrink-0" />
        <p>{m.no_completion_model_description()}</p>
      </div>
    </div>
  {/if}

  <PromptInput.Body>
    <MentionInput onpaste={queueUploadsFromClipboard}></MentionInput>
  </PromptInput.Body>

  {#if chat.settingsError}
    <div class="text-destructive flex items-center gap-2 px-3 py-2 text-sm" role="alert">
      <p>{m.conversation_settings_save_failed()} {getErrorMessage(chat.settingsError)}</p>
      <Button variant="ghost" size="sm" onclick={() => void chat.loadSettings(true)}
        >{m.conversation_settings_reload()}</Button
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

  <PromptInput.Footer>
    <PromptInput.Tools
      class={chat.askQuestion.isLoading ? "pointer-events-none opacity-40" : undefined}
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
          disabledServerIds={disabledMcpServerIds}
          onSelectionChange={persistMcpServerSelection}
          {autoAcceptTools}
          disabled={settingsDisabled}
          showApproval={chat.partner.type !== "group-chat"}
          onAutoAcceptChange={(enabled) =>
            void chat.updateSettings({ require_tool_approval: !enabled })}
        />
      {/if}
    </PromptInput.Tools>

    <!-- Right cluster: model + send/stop -->
    <div class="flex items-center gap-2">
      {#if showModelSelect}
        <ChatModelSelect onNewConversation={startNewConversation} />
        <ChatReasoningSelect />
      {/if}

      <PromptInput.Submit disabled={isAskingDisabled} name="ask" />
    </div>
  </PromptInput.Footer>
</PromptInput.Root>
