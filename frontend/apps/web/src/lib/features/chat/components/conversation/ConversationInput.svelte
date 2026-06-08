<script lang="ts">
  import { onMount } from "svelte";
  import { browser } from "$app/environment";
  import AttachmentUploadIconButton from "$lib/features/attachments/components/AttachmentUploadIconButton.svelte";
  import { IconEnter } from "@intric/icons/enter";
  import { IconStopCircle } from "@intric/icons/stop-circle";
  import { Button, Input, Tooltip } from "@intric/ui";
  import { getAttachmentManager } from "$lib/features/attachments/AttachmentManager";
  import MentionInput from "../mentions/MentionInput.svelte";
  import { initMentionInput } from "../mentions/MentionInput";
  import MentionButton from "../mentions/MentionButton.svelte";
  import { getChatService } from "../../ChatService.svelte";
  import { IconWeb } from "@intric/icons/web";
  import { track } from "$lib/core/helpers/track";
  import { getAppContext } from "$lib/core/AppContext";
  import { m } from "$lib/paraglide/messages";
  import { Wrench, AlertTriangle, Settings2 } from "lucide-svelte";
  import { getErrorMessage } from "$lib/core/errors/getErrorMessage";

  const chat = getChatService();
  const { featureFlags, settings } = getAppContext();

  const {
    state: { attachments, isUploading },
    queueValidUploads,
    clearUploads
  } = getAttachmentManager();

  const {
    states: { mentions, question },
    resetMentionInput,
    setQuestionText: _setQuestionText,
    focusMentionInput
  } = initMentionInput({
    triggerCharacter: "@",
    tools: () => chat.partner.tools,
    onEnterPressed: ask
  });

  type Props = { scrollToBottom: () => void; onNewConversation?: () => void };

  const { scrollToBottom, onNewConversation }: Props = $props();

  let abortController: AbortController | undefined;
  const AUTO_ACCEPT_TOOLS_STORAGE_KEY = "autoAcceptToolsEnabled";
  let autoAcceptTools = $state(true);
  let hasHydratedToolApprovalPreference = $state(false);

  onMount(() => {
    if (!browser) {
      hasHydratedToolApprovalPreference = true;
      return;
    }

    // Load auto-accept tools preference (default to true = auto-accept)
    try {
      const storedAutoAccept = window.localStorage.getItem(AUTO_ACCEPT_TOOLS_STORAGE_KEY);
      if (storedAutoAccept === "false") {
        autoAcceptTools = false;
      } else {
        autoAcceptTools = true;
        window.localStorage.setItem(AUTO_ACCEPT_TOOLS_STORAGE_KEY, "true");
      }
    } catch (error) {
      console.warn("Unable to read auto-accept tools preference", error);
    } finally {
      hasHydratedToolApprovalPreference = true;
    }
  });

  $effect(() => {
    if (!browser || !hasHydratedToolApprovalPreference) return;

    try {
      window.localStorage.setItem(
        AUTO_ACCEPT_TOOLS_STORAGE_KEY,
        autoAcceptTools ? "true" : "false"
      );
    } catch (error) {
      console.warn("Unable to persist auto-accept tools preference", error);
    }
  });

  function queueUploadsFromClipboard(event: ClipboardEvent) {
    if (!event.clipboardData?.files || event.clipboardData.files.length === 0) return;
    queueValidUploads([...event.clipboardData.files]);
  }

  let inputError = $state<{ message: string; details?: string; isContextError?: boolean } | null>(
    null
  );
  let errorInputSnapshot = { question: "", attachmentIds: "" };

  const startNewConversation = () => {
    inputError = null;
    errorInputSnapshot = { question: "", attachmentIds: "" };
    if (onNewConversation) onNewConversation();
    else chat.newConversation();
  };

  // Edit mode: only when the tenant has enabled it, and only for assistants the
  // user may edit.
  const canEditAssistant = $derived(
    (settings?.edit_mode_enabled ?? false) &&
      chat.partner.type === "assistant" &&
      "permissions" in chat.partner &&
      (chat.partner.permissions?.includes("edit") ?? false)
  );
  let editMode = $state(false);

  // Free-text answer for a standalone ask_user elicitation prompt.
  let elicitAnswer = $state("");

  function submitElicitAnswer() {
    if (!elicitAnswer.trim()) return;
    const answer = elicitAnswer;
    elicitAnswer = "";
    chat.submitElicitation("accept", answer);
  }

  function toggleEditMode(next: boolean) {
    editMode = next;
    // Start a fresh conversation so configuration messages aren't interleaved
    // with normal chat history (the assistant runs a different persona here).
    startNewConversation();
  }

  function parseTokenError(errorMessage: string): { used: number; limit: number } | null {
    const match = errorMessage.match(/(\d[\d,]*)\s*tokens?\s*used.*?limit\s*(?:is\s*)?(\d[\d,]*)/i);
    if (match) {
      return {
        used: parseInt(match[1].replace(/,/g, "")),
        limit: parseInt(match[2].replace(/,/g, ""))
      };
    }
    return null;
  }

  async function ask() {
    if (isAskingDisabled) return;
    inputError = null;
    const webSearchEnabled = featureFlags.showWebSearch && useWebSearch;
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
    const toolApprovalEnabled = !autoAcceptTools && hasMcpTools;
    scrollToBottom();

    try {
      await chat.askQuestion(
        $question,
        files,
        tools,
        webSearchEnabled,
        toolApprovalEnabled,
        abortController,
        editMode
      );
      resetMentionInput();
      clearUploads();
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      const lower = errorMessage.toLowerCase();
      const isContextError =
        lower.includes("context window") ||
        lower.includes("context length") ||
        lower.includes("tokens used") ||
        lower.includes("too long");

      if (isContextError) {
        const tokenInfo = parseTokenError(errorMessage);
        if (tokenInfo) {
          const excess = tokenInfo.used - tokenInfo.limit;
          inputError = {
            message: m.context_window_exceeded(),
            details: `${tokenInfo.used.toLocaleString()} / ${tokenInfo.limit.toLocaleString()} tokens (${excess.toLocaleString()} ${m.over()})`,
            isContextError: true
          };
        } else {
          inputError = { message: m.context_window_exceeded(), isContextError: true };
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

  let useWebSearch = $state(false);

  const shouldShowMentionButton = $derived.by(() => {
    const hasTools = chat.partner.tools.assistants.length > 0;
    const isEnabled =
      chat.partner.type === "default-assistant" ||
      ("allow_mentions" in chat.partner && chat.partner.allow_mentions);
    return hasTools && isEnabled;
  });

  // Check if the assistant has MCP servers/tools
  const hasMcpTools = $derived.by(() => {
    if (!chat.partner) return false;
    // Check for mcp_servers array on the partner
    if ("mcp_servers" in chat.partner && Array.isArray(chat.partner.mcp_servers)) {
      return chat.partner.mcp_servers.length > 0;
    }
    return false;
  });

  // Block sending while the local projection says the next message will
  // overflow the context window. Removes the need to round-trip the server
  // error path for the obvious case; the server still validates as the
  // authoritative source.
  const isAskingDisabled = $derived(
    chat.askQuestion.isLoading ||
      $isUploading ||
      ($question === "" && $attachments.length === 0) ||
      !chat.hasCompletionModel ||
      chat.willExceedContext
  );
</script>

<form
  onsubmit={async (e) => {
    e.preventDefault();
    await ask();
  }}
  class="border-default bg-primary ring-dimmer relative flex w-[100%] max-w-[74ch] flex-col border-t p-1.5 shadow-md ring-offset-0 transition-all duration-300 md:w-full md:rounded-xl md:border {chat.hasCompletionModel
    ? 'focus-within:border-stronger hover:border-stronger focus-within:shadow-lg hover:ring-4'
    : ''}"
>
  {#if !chat.hasCompletionModel}
    <div
      class="bg-primary/80 absolute inset-0 z-10 flex items-center justify-center rounded-xl backdrop-blur-[1px]"
    >
      <div class="text-secondary flex items-center gap-2 px-4 text-sm">
        <AlertTriangle class="h-4 w-4 flex-shrink-0" />
        <p>{m.no_completion_model_description()}</p>
      </div>
    </div>
  {/if}
  {#if editMode}
    <div
      class="text-accent-stronger bg-accent-dimmer border-accent-default mb-1.5 flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm"
    >
      <Settings2 class="h-4 w-4 flex-shrink-0" />
      <p>{m.edit_mode_banner()}</p>
    </div>
  {/if}

  {#if chat.pendingElicitation && !chat.pendingElicitation.toolCallId}
    {@const elicitation = chat.pendingElicitation}
    <div
      class="border-default bg-secondary mb-1.5 flex flex-col gap-2 rounded-lg border px-3 py-2.5 text-sm"
    >
      <p class="whitespace-pre-line">{elicitation.message}</p>
      {#if elicitation.answerField}
        {#if elicitation.suggestions.length > 0}
          <div class="flex flex-wrap gap-1.5">
            {#each elicitation.suggestions as suggestion (suggestion)}
              <button
                type="button"
                class="border-default hover:bg-hover-default rounded-full border px-3 py-1"
                onclick={() => chat.submitElicitation("accept", suggestion)}
              >
                {suggestion}
              </button>
            {/each}
          </div>
        {/if}
        <div class="flex gap-2">
          <input
            type="text"
            bind:value={elicitAnswer}
            placeholder={m.elicitation_answer_placeholder()}
            class="border-default bg-primary flex-1 rounded-lg border px-3 py-1.5"
            onkeydown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                submitElicitAnswer();
              }
            }}
          />
          <Button variant="primary" disabled={!elicitAnswer.trim()} onclick={submitElicitAnswer}>
            {m.send()}
          </Button>
          <Button variant="outlined" onclick={() => chat.submitElicitation("decline")}>
            {m.decline()}
          </Button>
        </div>
      {:else}
        <div class="flex gap-2">
          <Button variant="primary" onclick={() => chat.submitElicitation("accept")}>
            {m.confirm()}
          </Button>
          <Button variant="outlined" onclick={() => chat.submitElicitation("decline")}>
            {m.decline()}
          </Button>
        </div>
      {/if}
    </div>
  {/if}

  <div class="relative">
    <MentionInput onpaste={queueUploadsFromClipboard}></MentionInput>
    {#if chat.askQuestion.isLoading}
      <div
        class="bg-primary/60 absolute inset-0 flex items-center justify-center rounded-lg backdrop-blur-[1px]"
      >
        <div class="text-secondary flex items-center gap-2 text-sm">
          <svg class="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"
            ></circle>
            <path
              class="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
            ></path>
          </svg>
          {m.generating_answer()}
        </div>
      </div>
    {/if}
  </div>

  {#if inputError}
    <div
      class="text-negative-stronger bg-negative-dimmer/30 mt-1 flex items-start justify-between gap-2 rounded-md px-2 py-1.5 text-sm"
    >
      <div class="flex items-start gap-2">
        <AlertTriangle class="mt-0.5 h-4 w-4 flex-shrink-0" />
        <div>
          <p class="font-medium">{inputError.message}</p>
          {#if inputError.details}
            <p class="text-negative-stronger mt-0.5">{inputError.details}</p>
          {/if}
        </div>
      </div>
      {#if inputError.isContextError}
        <button
          type="button"
          onclick={startNewConversation}
          class="border-negative-stronger/40 hover:bg-negative-dimmer/50 ml-2 flex-shrink-0 self-center rounded-md border px-2 py-1 text-xs font-medium whitespace-nowrap transition-colors"
        >
          {m.new_conversation()}
        </button>
      {/if}
    </div>
  {/if}

  <div class="mt-2 flex justify-between">
    <div
      class="flex items-center gap-2 {chat.askQuestion.isLoading
        ? 'pointer-events-none opacity-40'
        : ''}"
    >
      <AttachmentUploadIconButton label={m.upload_documents_to_conversation()} />
      {#if shouldShowMentionButton}
        <MentionButton></MentionButton>
      {/if}

      {#if chat.partner.type === "default-assistant" && featureFlags.showWebSearch}
        <div
          class="hover:bg-accent-dimmer hover:text-accent-stronger border-default hover:border-accent-default flex items-center justify-center rounded-full border p-1.5"
        >
          <Input.Switch bind:value={useWebSearch} class="*:!cursor-pointer">
            <span class="-mr-2 flex gap-1"><IconWeb></IconWeb>{m.search()}</span></Input.Switch
          >
        </div>
      {/if}

      {#if hasMcpTools}
        <Tooltip
          text={autoAcceptTools ? m.auto_accept_tools_on() : m.auto_accept_tools_off()}
          placement="top"
        >
          <div
            class="hover:bg-accent-dimmer hover:text-accent-stronger border-default hover:border-accent-default flex items-center justify-center rounded-full border p-1.5 {autoAcceptTools
              ? 'bg-accent-dimmer text-accent-stronger border-accent-default'
              : ''}"
          >
            <Input.Switch bind:value={autoAcceptTools} class="*:!cursor-pointer">
              <span class="-mr-2 flex items-center gap-1"
                ><Wrench class="h-5 w-5" />{m.auto_accept_tools()}</span
              >
            </Input.Switch>
          </div>
        </Tooltip>
      {/if}

      {#if canEditAssistant}
        <Tooltip text={m.edit_mode_description()} placement="top">
          <div
            class="hover:bg-accent-dimmer hover:text-accent-stronger border-default hover:border-accent-default flex items-center justify-center rounded-full border p-1.5 {editMode
              ? 'bg-accent-dimmer text-accent-stronger border-accent-default'
              : ''}"
          >
            <Input.Switch
              value={editMode}
              sideEffect={({ next }) => toggleEditMode(next)}
              class="*:!cursor-pointer"
            >
              <span class="-mr-2 flex items-center gap-1"
                ><Settings2 class="h-5 w-5" />{m.edit_mode()}</span
              >
            </Input.Switch>
          </div>
        </Tooltip>
      {/if}
    </div>

    <div class="flex items-center gap-2">
      {#if chat.askQuestion.isLoading}
        <Tooltip text={m.cancel_your_request()} placement="top" let:trigger asFragment>
          <Button
            unstyled
            aria-label={m.cancel_your_request()}
            type="button"
            is={trigger}
            onclick={() => abortController?.abort("User cancelled")}
            name="ask"
            class="bg-secondary hover:bg-hover-stronger disabled:bg-tertiary disabled:text-secondary flex h-9 items-center justify-center !gap-1 rounded-lg !pr-1 !pl-2"
          >
            {m.stop_answer()}
            <IconStopCircle />
          </Button>
        </Tooltip>
      {:else}
        <Button
          disabled={isAskingDisabled}
          aria-label={m.submit_your_question()}
          type="submit"
          name="ask"
          class="bg-secondary hover:bg-hover-stronger disabled:bg-tertiary disabled:text-secondary flex h-9 items-center justify-center !gap-1 rounded-lg !pr-1 !pl-2"
        >
          {m.send()}
          <IconEnter />
        </Button>
      {/if}
    </div>
  </div>
</form>
