<script lang="ts">
  import { onMount, untrack } from "svelte";
  import { browser } from "$app/environment";
  import AttachmentUploadIconButton from "$lib/features/attachments/components/AttachmentUploadIconButton.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as PromptInput from "$lib/components/ai-elements/prompt-input/index.js";
  import { getAttachmentManager } from "$lib/features/attachments/AttachmentManager";
  import MentionInput from "../mentions/MentionInput.svelte";
  import { initMentionInput } from "../mentions/MentionInput";
  import MentionButton from "../mentions/MentionButton.svelte";
  import ChatModelSelect from "../switcher/ChatModelSelect.svelte";
  import ChatMcpServers from "./ChatMcpServers.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getChatService } from "../../ChatService.svelte";
  import { track } from "$lib/core/helpers/track";
  import { getAppContext } from "$lib/core/AppContext";
  import { m } from "$lib/paraglide/messages";
  import { SvelteSet } from "svelte/reactivity";
  import { Globe, AlertTriangle } from "lucide-svelte";
  import { getErrorMessage } from "$lib/core/errors/getErrorMessage";

  type McpServerSummary = {
    id: string;
    name: string;
    description?: string | null;
    icon_url?: string | null;
  };

  const chat = getChatService();
  const { featureFlags } = getAppContext();

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

  // MCP servers the user has switched OFF in the toolbar popover for this
  // conversation; everything else stays active. Sent with each ask request so
  // the backend narrows the effective server set accordingly. Mutated in place
  // by ChatMcpServers.
  const disabledMcpServerIds = new SvelteSet<string>();

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
        disabledMcpServerIds.size > 0 ? Array.from(disabledMcpServerIds) : undefined
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
    // Also re-run on a partner/model switch: the personal-chat model picker
    // replaces the partner object, and the estimate (and its context window)
    // must track the model that will actually answer, not the one that was
    // active when the user started typing.
    track(chat.partner);
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

  $effect(() => {
    const validIds = new Set(mcpServers.map((server) => server.id));
    for (const id of Array.from(disabledMcpServerIds)) {
      if (!validIds.has(id)) disabledMcpServerIds.delete(id);
    }
  });

  // Seed the toggles from the governance policy's per-server chat defaults.
  // Keyed on the conversation OBJECT: ChatService replaces it on new/loaded
  // conversations but mutates it while a conversation is running, so the seed
  // never wipes toggles the user made mid-conversation.
  let seededConversation: unknown = null;
  $effect(() => {
    const conversation = chat.currentConversation;
    const partner = chat.partner;
    if (conversation === seededConversation) return;
    seededConversation = conversation;
    untrack(() => {
      disabledMcpServerIds.clear();
      if (partner && "effective_config" in partner) {
        for (const id of partner.effective_config?.default_disabled_mcp_server_ids ?? []) {
          disabledMcpServerIds.add(id);
        }
      }
    });
  });

  // Check if the assistant has MCP servers/tools
  const hasMcpTools = $derived(mcpServers.length > 0);

  const showWebSearch = $derived(
    chat.partner.type === "default-assistant" && featureFlags.showWebSearch
  );
  // ChatModelSelect edits the personal space's default assistant via the
  // SpacesManager context, which only the spaces route tree provides. Other
  // mounts of the default assistant (e.g. a deep link into the dashboard chat)
  // have no such context, so gate on its presence or the picker throws on init.
  const spacesManager = getSpacesManager();
  const showModelSelect = $derived(
    chat.partner.type === "default-assistant" && Boolean(spacesManager)
  );

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

<PromptInput.Root
  status={chat.askQuestion.isLoading ? "streaming" : "ready"}
  onSubmit={ask}
  onStop={() => abortController?.abort("User cancelled")}
  class="max-w-[74ch] md:w-full"
>
  {#if !chat.hasCompletionModel}
    <div
      class="bg-card/80 absolute inset-0 z-10 flex items-center justify-center rounded-2xl backdrop-blur-[1px]"
    >
      <div class="text-muted-foreground flex items-center gap-2 px-4 text-sm">
        <AlertTriangle class="h-4 w-4 flex-shrink-0" />
        <p>{m.no_completion_model_description()}</p>
      </div>
    </div>
  {/if}

  <PromptInput.Body>
    <MentionInput onpaste={queueUploadsFromClipboard}></MentionInput>
    {#if chat.askQuestion.isLoading}
      <div
        class="bg-card/60 absolute inset-0 flex items-center justify-center rounded-lg backdrop-blur-[1px]"
      >
        <div class="text-muted-foreground flex items-center gap-2 text-sm">
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
  </PromptInput.Body>

  {#if inputError}
    <div
      class="text-destructive bg-destructive/10 mx-1.5 mt-1 flex items-start justify-between gap-2 rounded-md px-2 py-1.5 text-sm"
    >
      <div class="flex items-start gap-2">
        <AlertTriangle class="mt-0.5 h-4 w-4 flex-shrink-0" />
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

      {#if hasMcpTools}
        <ChatMcpServers
          servers={mcpServers}
          disabledServerIds={disabledMcpServerIds}
          bind:autoAcceptTools
        />
      {/if}

      {#if showWebSearch}
        <PromptInput.Button
          variant={useWebSearch ? "secondary" : "ghost"}
          onclick={() => (useWebSearch = !useWebSearch)}
          title={m.search()}
        >
          <Globe class="size-4" />
          <span class="hidden sm:inline">{m.search()}</span>
        </PromptInput.Button>
      {/if}
    </PromptInput.Tools>

    <!-- Right cluster: model + send/stop -->
    <div class="flex items-center gap-2">
      {#if showModelSelect}
        <ChatModelSelect />
      {/if}

      <PromptInput.Submit disabled={isAskingDisabled} name="ask" />
    </div>
  </PromptInput.Footer>
</PromptInput.Root>
