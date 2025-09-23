<script lang="ts">
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
  import TokenUsageBar from "$lib/features/tokens/TokenUsageBar.svelte";
  import { getIntric } from "$lib/core/Intric";

  const chat = getChatService();
  const { featureFlags } = getAppContext();
  const intric = getIntric();

  const {
    state: { attachments, isUploading },
    queueValidUploads,
    clearUploads
  } = getAttachmentManager();

  const {
    states: { mentions, question },
    resetMentionInput,
    focusMentionInput
  } = initMentionInput({
    triggerCharacter: "@",
    tools: () => chat.partner.tools,
    onEnterPressed: ask
  });

  type Props = { scrollToBottom: () => void };

  const { scrollToBottom }: Props = $props();

  let abortController: AbortController | undefined;

  function queueUploadsFromClipboard(event: ClipboardEvent) {
    if (!event.clipboardData) return;
    if (!event.clipboardData.files) return;
    if (!(event.clipboardData.files.length > 0)) return;

    queueValidUploads([...event.clipboardData.files]);
  }

  function ask() {
    if (isAskingDisabled) return;
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
    chat.askQuestion($question, files, tools, webSearchEnabled, abortController);
    scrollToBottom();
    resetMentionInput();
    clearUploads();
  }

  $effect(() => {
    track(chat.partner, chat.currentConversation);
    focusMentionInput();
  });

  const isAskingDisabled = $derived(
    chat.askQuestion.isLoading || $isUploading || ($question === "" && $attachments.length === 0)
  );

  let useWebSearch = $state(false);

  const shouldShowMentionButton = $derived.by(() => {
    const hasTools = chat.partner.tools.assistants.length > 0;
    const isEnabled =
      chat.partner.type === "default-assistant" ||
      ("allow_mentions" in chat.partner && chat.partner.allow_mentions);
    return hasTools && isEnabled;
  });

  // Token counting logic
  // Use more accurate approximation: average 3.8 chars per token for English text
  const textTokens = $derived(Math.ceil($question.length / 3.8));

  // Store file token counts fetched from API
  let fileTokenCounts = $state<Record<string, number>>({});

  // Track which files we're currently fetching tokens for to avoid duplicate requests
  let fetchingTokensFor = new Set<string>();

  // Debounce timer
  let tokenFetchTimer: ReturnType<typeof setTimeout> | null = null;

  // Sum tokens from uploaded files
  const fileTokens = $derived(
    $attachments.reduce((sum, att) => {
      if (att.fileRef?.id) {
        return sum + (fileTokenCounts[att.fileRef.id] || 0);
      }
      return sum;
    }, 0)
  );

  // Get model info from assistant (if available)
  // This comes from the assistant endpoint with actual model's token_limit from ai_models.yml
  const modelInfo = $derived(chat.partner?.model_info || null);
  const promptTokens = $derived(modelInfo?.prompt_tokens || 0);
  const tokenLimit = $derived(modelInfo?.token_limit || 0);  // No default - comes from backend

  // Total tokens
  const totalTokens = $derived(promptTokens + fileTokens + textTokens);

  // Text is always approximate when typing, exact when we have file counts
  const isApproximate = $derived($question.length > 0);

  // Fetch token counts when attachments change (debounced)
  $effect(() => {
    const currentFileIds = $attachments
      .filter(att => att.fileRef?.id)
      .map(att => att.fileRef!.id);

    // Clean up token counts for removed files
    const currentFileIdSet = new Set(currentFileIds);
    for (const fileId of Object.keys(fileTokenCounts)) {
      if (!currentFileIdSet.has(fileId)) {
        delete fileTokenCounts[fileId];
      }
    }

    // Find files that need token counting (new files not already being fetched)
    const filesNeedingTokens = currentFileIds.filter(
      id => !(id in fileTokenCounts) && !fetchingTokensFor.has(id)
    );

    if (filesNeedingTokens.length > 0 && chat.partner?.id) {
      // Cancel any pending fetch
      if (tokenFetchTimer) {
        clearTimeout(tokenFetchTimer);
      }

      // Debounce the fetch to wait for all files to be added
      tokenFetchTimer = setTimeout(() => {
        fetchFileTokens(filesNeedingTokens);
      }, 200); // 200ms debounce
    }
  });

  async function fetchFileTokens(fileIds: string[]) {
    if (fileIds.length === 0) return;

    // Mark these files as being fetched
    fileIds.forEach(id => fetchingTokensFor.add(id));

    try {
      // Use the intric client to make the API call
      const response = await intric.client.fetch("/api/v1/assistants/{id}/token-estimate", {
        method: "get",
        params: {
          path: { id: chat.partner.id },
          query: {
            file_ids: fileIds.join(','),
            text: ''  // Empty text for now, just counting files
          }
        }
      });

      if (response) {
        // Use per-file breakdown if available
        if (response.breakdown?.file_details) {
          // Merge new token counts with existing ones (don't overwrite all)
          Object.assign(fileTokenCounts, response.breakdown.file_details);
        } else if (response.breakdown?.files) {
          // Fallback: distribute total file tokens equally
          const tokensPerFile = Math.ceil(response.breakdown.files / fileIds.length);
          fileIds.forEach(id => {
            fileTokenCounts[id] = tokensPerFile;
          });
        }
      }
    } catch (error) {
      console.error('Failed to fetch token estimates:', error);
      // Fallback: estimate based on file size if available
      fileIds.forEach(fileId => {
        const attachment = $attachments.find(att => att.fileRef?.id === fileId);
        if (attachment?.fileRef?.size) {
          // Rough estimate: 1 token per 4 bytes
          fileTokenCounts[fileId] = Math.ceil(attachment.fileRef.size / 4);
        }
      });
    } finally {
      // Clear the fetching set for these files
      fileIds.forEach(id => fetchingTokensFor.delete(id));
    }
  }
</script>

<!-- This interaction is just a convenience function -->
<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<!-- svelte-ignore a11y_click_events_have_key_events -->
<form
  onclick={() => {
    focusMentionInput();
  }}
  class="border-default bg-primary ring-dimmer focus-within:border-stronger hover:border-stronger flex w-[100%] max-w-[74ch] flex-col gap-2 border-t p-1.5 shadow-md ring-offset-0 transition-colors duration-300 focus-within:shadow-lg hover:ring-4 md:w-full md:rounded-xl md:border"
>
  <!-- Token usage indicator -->
  {#if modelInfo && tokenLimit > 0}
    <div class="px-2 pt-1">
      <TokenUsageBar tokens={totalTokens} limit={tokenLimit} isApproximate={isApproximate} />
    </div>
  {/if}

  <MentionInput onpaste={queueUploadsFromClipboard}></MentionInput>

  <div class="flex justify-between">
    <div class="flex items-center gap-2">
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
    </div>

    {#if chat.askQuestion.isLoading}
      <Tooltip text={m.cancel_your_request()} placement="top" let:trigger asFragment>
        <Button
          unstyled
          aria-label={m.cancel_your_request()}
          type="submit"
          is={trigger}
          on:click={() => abortController?.abort("User cancelled")}
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
        on:click={() => ask()}
        name="ask"
        class="bg-secondary hover:bg-hover-stronger disabled:bg-tertiary disabled:text-secondary flex h-9 items-center justify-center !gap-1 rounded-lg !pr-1 !pl-2"
      >
        {m.send()}
        <IconEnter />
      </Button>
    {/if}
  </div>
</form>
