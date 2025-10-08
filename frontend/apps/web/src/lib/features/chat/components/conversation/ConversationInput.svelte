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

  const shouldShowMentionButton = $derived.by(() => {
    const hasTools = chat.partner.tools.assistants.length > 0;
    const isEnabled =
      chat.partner.type === "default-assistant" ||
      ("allow_mentions" in chat.partner && chat.partner.allow_mentions);
    return hasTools && isEnabled;
  });
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
