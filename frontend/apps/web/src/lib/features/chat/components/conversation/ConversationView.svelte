<script lang="ts">
  import { conversationUploads } from "../../conversationUploads";
  import { opensFilePanel } from "../../toolFileInputs";
  import { getEneo } from "$lib/core/Eneo";
  import { initAttachmentManager } from "$lib/features/attachments/AttachmentManager";
  import { getAttachmentRulesStore } from "$lib/features/attachments/getAttachmentRules";
  import { toStore } from "svelte/store";
  import AttachmentDropArea from "$lib/features/attachments/components/AttachmentDropArea.svelte";
  import { getAttachmentUrlService } from "$lib/features/attachments/AttachmentUrlService.svelte";
  import {
    getFilePreview,
    initFilePreview,
    type DocumentExport
  } from "$lib/features/file-preview/FilePreview.svelte";
  import { previewKindOf, type PreviewFile } from "$lib/features/file-preview/previewKind";
  import FilePreviewLayout from "$lib/features/file-preview/components/FilePreviewLayout.svelte";
  import { IconArrowDownToLine } from "@eneo/icons/arrow-down-to-line";
  import { Markdown } from "$lib/components/markdown/index.js";
  import Message from "./Message.svelte";
  import ChatComposer from "./ChatComposer.svelte";
  import { fade } from "svelte/transition";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { getChatService } from "../../ChatService.svelte";
  import { editedPassage } from "../../documentVersions";
  import { chatCapabilityAvailable } from "../../chatCapabilities";
  import type { PanelContents } from "$lib/features/file-preview/panelContents";
  import { getAppContext } from "$lib/core/AppContext";
  import { untrack, type Snippet } from "svelte";
  import { followConversationScroll } from "../../followConversationScroll";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    children?: Snippet;
    onNewConversation?: () => void;
  };

  let { children, onNewConversation }: Props = $props();

  const chat = getChatService();
  const uploads = $derived(conversationUploads(chat.currentConversation.messages ?? []));
  const { user } = getAppContext();

  // Validate uploads client-side against the backend's per-format size limits
  // (and the partner model's vision support) so oversized or unsupported files
  // are rejected instantly with a clear message instead of silently failing the
  // server-side request. Group-chat partners have no completion_model, so vision
  // formats are simply omitted from the accepted set. Images are also accepted
  // when image generation is available: the model can hand them to the image
  // tool as reference images even without seeing them itself.
  const attachmentRules = getAttachmentRulesStore(
    toStore(() => {
      const partner = chat.partner;
      const completion_model =
        partner && "completion_model" in partner ? partner.completion_model : null;
      return {
        completion_model,
        acceptsImageAttachments:
          completion_model?.vision === true ||
          chatCapabilityAvailable(partner, user, "image_generation")
      };
    })
  );
  initAttachmentManager({
    eneo: getEneo(),
    options: { rules: attachmentRules, inlineErrors: true }
  });

  // Every file in the conversation opens in one preview panel beside the
  // messages. Reuse page-owned state across chat/history tabs when available;
  // otherwise the conversation owns it.
  const filePreview = getFilePreview() ?? initFilePreview(getAttachmentUrlService());

  // The panel follows the conversation: a previewed file that is no longer
  // among the messages (another conversation or assistant was opened) closes,
  // and a quote taken from such a file is dropped from the composer.
  $effect(() => {
    const previewedId = filePreview.file?.id;
    const quotedId = filePreview.quote?.fileId;
    if (!previewedId && !quotedId) return;
    const present = (fileId: string | undefined) =>
      (chat.currentConversation.messages ?? []).some(
        (message) =>
          message.files?.some((file) => file.id === fileId) ||
          message.generated_files?.some((file) => file.id === fileId)
      );
    if (previewedId && !present(previewedId)) untrack(() => filePreview.close());
    if (quotedId && !present(quotedId)) filePreview.quote = null;
  });

  // The panel follows the answer being written. A document draft shows
  // there while the assistant writes it, and a file created in the live turn
  // (typically the revision of the document on show) takes the panel over, so
  // an edit is seen without reopening anything. Files of a conversation loaded
  // from history are only noted, never opened.
  $effect(() => {
    const streaming = chat.askQuestion.isLoading;
    untrack(() => (streaming ? filePreview.beginAnswer() : filePreview.endDraft()));
  });
  $effect(() => {
    const draft = chat.writingDocument;
    if (draft) untrack(() => filePreview.write(draft));
  });
  // A Markdown document the assistant made here can be handed over as Word or
  // PDF: the assistant's own document tool renders it, when it has one.
  const eneo = getEneo();
  function documentExport(file: PreviewFile): DocumentExport | null {
    const sessionId = chat.currentConversation.id;
    if (!sessionId || previewKindOf(file) !== "markdown") return null;
    if (chat.documents.versionsOf(file.id).length === 0) return null;
    return {
      availability: () =>
        eneo.conversations.getDocumentExportAvailability({ sessionId, fileId: file.id }),
      exportAs: (format) =>
        eneo.conversations.exportDocument({ sessionId, fileId: file.id, format })
    };
  }

  // A tool call of the answer being written.
  type LiveToolCall = Parameters<typeof chat.generatedFileIdsOf>[0] & {
    arguments?: Record<string, unknown> | null;
    purpose?: string | null;
  };
  let newestFileId = "";
  $effect(() => {
    const streaming = chat.askQuestion.isLoading;
    const newest = chat.currentConversation.messages
      ?.at(-1)
      ?.generated_files?.findLast((file) => file.id && filePreview.canPreview(file));
    if (!newest || newest.id === newestFileId) return;
    if (!streaming) {
      newestFileId = newest.id;
      return;
    }
    // Files arrive before their final tool metadata. Wait until their producer
    // is known so hidden analysis exports never replace the user's preview.
    const last = chat.currentConversation.messages?.at(-1) as
      { mcp_tool_calls?: LiveToolCall[] } | undefined;
    const call = last?.mcp_tool_calls?.find((made) =>
      chat.generatedFileIdsOf(made).includes(newest.id)
    );
    if (!call) return;
    newestFileId = newest.id;
    if (!opensFilePanel(call)) return;
    untrack(() => {
      const changed = editedPassage(call?.arguments);
      filePreview.arrive(
        newest,
        changed ? { text: changed, locator: null } : null,
        call.tool_call_id
      );
    });
  });

  let scrollContainer = $state<HTMLDivElement>();
  let messageContainer = $state<HTMLDivElement>();
  let inputContainer = $state<HTMLDivElement>();
  let showScrollToBottom = $state(false);
  let scrollFollower: ReturnType<typeof followConversationScroll> | undefined;

  const scrollToBottom = () => scrollFollower?.toBottom();

  $effect(() => {
    const container = scrollContainer;
    const messages = messageContainer;
    const input = inputContainer;
    // A newly opened conversation starts at its latest message.
    const conversationId = chat.currentConversation.id;
    void conversationId;
    if (!container || !input) return;
    const follower = untrack(() =>
      followConversationScroll(
        container,
        [messages, input].filter((element): element is HTMLDivElement => !!element),
        (away) => {
          showScrollToBottom = away;
        }
      )
    );
    scrollFollower = follower;
    return () => {
      follower.destroy();
      if (scrollFollower === follower) scrollFollower = undefined;
    };
  });

  // An interactive tool view that asks for more room shares the panel with
  // the file preview. The view covers the file, which is shown again when the
  // view closes; a file that is opened sends the view back to its answer.
  const panelContents = $derived<PanelContents>({
    views: [],
    documents: chat.documents.documents,
    uploads
  });

  let isDragging = $state(false);
</script>

<FilePreviewLayout
  preview={filePreview}
  versionsOf={(file) => chat.documents.versionsOf(file.id)}
  exportOf={documentExport}
  contents={panelContents}
>
  <div class="flex h-full min-h-0 min-w-0 flex-col">
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="md:stable-gutter relative flex min-h-0 flex-1 flex-col overflow-y-auto"
      id="session-view-container"
      bind:this={scrollContainer}
      ondragenter={(event) => {
        event.preventDefault();
        isDragging = true;
      }}
    >
      {#if chat.currentConversation.messages && chat.currentConversation.messages.length > 0}
        <div
          class="flex flex-grow flex-col gap-2 p-4 md:p-8"
          aria-live="polite"
          id="session-message-container"
          bind:this={messageContainer}
        >
          <!-- Keyed by object identity: streamed messages are mutated in place and
             the approval-race message keeps an empty id forever, so neither the
             index nor the id is a stable key. Identity keying keeps stateful
             children (MCP app iframes) mounted across list shifts. -->
          {#each chat.currentConversation.messages as message, idx (message)}
            <Message
              {message}
              isLast={idx === chat.currentConversation.messages.length - 1}
              isLoading={chat.askQuestion.isLoading}
            ></Message>
          {/each}
        </div>
      {:else if !chat.hasCompletionModel}
        <div class="flex flex-grow items-center justify-center">
          <p class="text-secondary max-w-[50ch] text-center text-sm">
            {m.no_completion_model_description()}
          </p>
        </div>
      {:else if children}
        <div class="flex flex-grow flex-col items-center justify-center">
          {@render children?.()}
        </div>
      {:else}
        <div class="flex flex-grow items-center justify-center">
          <div class="text-primary max-h-[80%] max-w-[50ch] overflow-x-auto">
            <Markdown
              class="flex flex-col items-center justify-center gap-4 *:m-0 [&_p]:text-center"
              source={"description" in chat.partner && chat.partner.description
                ? chat.partner.description
                : m.assistant_placeholder({ name: chat.partner?.name ?? "" })}
            ></Markdown>
          </div>
        </div>
      {/if}
      <div
        id="session-input-container"
        bind:this={inputContainer}
        class="sticky inset-x-0 bottom-0 flex flex-col items-center justify-end gap-2 bg-gradient-to-b from-transparent to-[var(--background-primary)] p-0 backdrop-blur-sm md:gap-4 md:p-6 md:pt-0"
      >
        {#if showScrollToBottom}
          <div transition:fade={{ duration: 150 }} class="absolute -top-12">
            <Tooltip.Root>
              <Tooltip.Trigger
                class="border-stronger bg-primary ring-default hover:bg-secondary flex gap-1 rounded-full border px-1.5 py-1.5 shadow-lg ring-offset-0 hover:ring-2"
                aria-label={m.scroll_to_bottom()}
                onclick={scrollToBottom}
                ><IconArrowDownToLine></IconArrowDownToLine></Tooltip.Trigger
              >
              <Tooltip.Content>{m.scroll_to_bottom()}</Tooltip.Content>
            </Tooltip.Root>
          </div>
        {/if}
        <ChatComposer {scrollToBottom} {onNewConversation}></ChatComposer>
      </div>
    </div>
  </div>
</FilePreviewLayout>
{#if isDragging}
  <AttachmentDropArea bind:isDragging label={m.drop_files_here_conversation()} inlineErrors />
{/if}

<style></style>
