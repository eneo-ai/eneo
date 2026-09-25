<script lang="ts">
  import type { App } from "@eneo/eneo-js";
  import {
    getAttachmentManager,
    unsupportedTypeError,
    type AttachmentValidationError
  } from "$lib/features/attachments/AttachmentManager";
  import AttachmentItem from "$lib/features/attachments/components/AttachmentItem.svelte";
  import FileDropzone, {
    type FileSelection
  } from "$lib/features/attachments/components/FileDropzone.svelte";
  import FileSizeValidationPanel from "$lib/features/attachments/components/FileSizeValidationPanel.svelte";
  import { getExplicitAttachmentRules } from "$lib/features/attachments/getAttachmentRules";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    input: App["input_fields"][number];
    description?: string;
  };

  let { input, description }: Props = $props();

  const {
    queueValidUploadsDetailed,
    state: { attachments }
  } = getAttachmentManager();

  const attachmentRules = $derived(getExplicitAttachmentRules(input));
  const canAddMore = $derived(
    attachmentRules.maxTotalCount ? $attachments.length < attachmentRules.maxTotalCount : true
  );

  let validationErrors = $state<AttachmentValidationError[]>([]);

  function handleSelection({ accepted, rejected }: FileSelection) {
    const errors =
      accepted.length > 0 ? (queueValidUploadsDetailed(accepted, attachmentRules) ?? []) : [];
    validationErrors = [...rejected.map(unsupportedTypeError), ...errors];
  }
</script>

<div class="flex w-[60ch] max-w-full flex-col gap-2">
  {#if $attachments.length > 0}
    <div class="border-default bg-primary rounded-lg border p-2">
      {#each $attachments as attachment (attachment.id)}
        <AttachmentItem {attachment}></AttachmentItem>
      {/each}
    </div>
  {/if}

  {#if canAddMore}
    <FileDropzone
      formats={attachmentRules.acceptedFormats ?? []}
      keepSelection={false}
      description={description ?? m.upload_files_description()}
      onselect={handleSelection}
    />
  {/if}

  <FileSizeValidationPanel errors={validationErrors} />
</div>
