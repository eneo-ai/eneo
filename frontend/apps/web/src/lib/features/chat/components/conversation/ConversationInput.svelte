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

  // Disable web search when there are attachments
  $effect(() => {
    if ($attachments.length > 0 && useWebSearch) {
      useWebSearch = false;
    }
  });

  const shouldShowMentionButton = $derived.by(() => {
    const hasTools = chat.partner.tools.assistants.length > 0;
    const isEnabled =
      chat.partner.type === "default-assistant" ||
      ("allow_mentions" in chat.partner && chat.partner.allow_mentions);
    return hasTools && isEnabled;
  });
</script>

<div class="flex w-[100%] max-w-[74ch] flex-col md:w-full">
  {#if useWebSearch}
    <div class="bg-red-100 text-red-800 border-l border-r border-t border-red-300 text-sm px-3 py-2 rounded-t-xl text-center md:rounded-t-xl">
      {m.websearch_notice()}
    </div>
  {/if}

  <!-- This interaction is just a convenience function -->
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <form
    onclick={() => {
      focusMentionInput();
    }}
    class="{useWebSearch ? 'border-red-300 focus-within:border-red-400 hover:border-red-400' : 'border-default focus-within:border-stronger hover:border-stronger'} bg-primary ring-dimmer flex flex-col gap-2 border-t p-1.5 shadow-md ring-offset-0 transition-colors duration-300 focus-within:shadow-lg hover:ring-4 {useWebSearch ? 'rounded-b-xl rounded-t-none border-l border-r border-b md:rounded-b-xl md:rounded-t-none' : 'rounded-xl border'} md:border"
  >
  <MentionInput onpaste={queueUploadsFromClipboard}></MentionInput>

  <div class="flex justify-between">
    <div class="flex items-center gap-2">
      <AttachmentUploadIconButton disabled={useWebSearch} label={m.upload_documents_to_conversation()} />
      {#if shouldShowMentionButton}
        <MentionButton></MentionButton>
      {/if}
      {#if chat.partner.type === "default-assistant" && featureFlags.showWebSearch}
        <div
          class="border-default flex items-center justify-center rounded-full border p-1.5 {$attachments.length > 0 ? 'opacity-50 cursor-not-allowed' : 'hover:bg-accent-dimmer hover:text-accent-stronger hover:border-accent-default'}"
        >
          <Input.Switch bind:value={useWebSearch} disabled={$attachments.length > 0} class="{$attachments.length > 0 ? '*:!cursor-not-allowed' : '*:!cursor-pointer'}">
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
</div>
