<script lang="ts">
  import { onMount } from "svelte";
  import { getAppContext } from "$lib/core/AppContext";
  import { getJobManager } from "$lib/features/jobs/JobManager";
  import { getIntric } from "$lib/core/Intric";
  import type { AttachmentValidationError } from "$lib/features/attachments/AttachmentManager";
  import FileSizeValidationPanel from "$lib/features/attachments/components/FileSizeValidationPanel.svelte";
  import { type Group, type InfoBlob } from "@intric/intric-js";
  import { Button, Dialog, Input } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  const {
    limits,
    user,
    state: { showHeader }
  } = getAppContext();
  const acceptedMimeTypes = limits.info_blobs.formats.map((format) => format.mimetype);
  const formatLimitByType = new Map(limits.info_blobs.formats.map((format) => [format.mimetype, format.size]));

  const {
    queueUploads,
    state: { showJobManagerPanel }
  } = getJobManager();
  export let collection: Group;
  export let currentBlobs: InfoBlob[];
  export let disabled = false;

  let files: File[] = [];
  let fileValidationErrors: AttachmentValidationError[] = [];
  let quotaValidationError: AttachmentValidationError | null = null;
  let validationErrors: AttachmentValidationError[] = [];
  let quotaRemaining: number | null = null;
  let tenantQuotaLimit: number | null = null;
  let tenantQuotaUsed = 0;
  let isUploading = false;

  const intric = getIntric();

  onMount(async () => {
    try {
      const summary = await intric.usage.storage.getSummary();
      tenantQuotaLimit = summary.limit ?? null;
      tenantQuotaUsed = summary.total_used ?? 0;
    } catch (error) {
      console.error("BlobUpload: Failed to load storage summary", error);
    }
  });

  $: {
    const errors: AttachmentValidationError[] = [];
    for (const file of files) {
      if (!acceptedMimeTypes.includes(file.type)) {
        errors.push({
          kind: "unsupported_type",
          fileName: file.name,
          message: `${file.name}: File type "${file.type || "unknown"}" is not supported.`
        });
        continue;
      }
      const limit = formatLimitByType.get(file.type);
      if (limit !== undefined && file.size > limit) {
        errors.push({
          kind: "file_size",
          message: `${file.name}: file is too large.`,
          fileName: file.name,
          fileSizeBytes: file.size,
          maxSizeBytes: limit
        });
      }
    }
    fileValidationErrors = errors;
  }

  $: {
    const remainingCandidates: number[] = [];
    if (user.quota_limit != null) {
      const quotaUsed = user.quota_used ?? 0;
      remainingCandidates.push(user.quota_limit - quotaUsed);
    }
    if (tenantQuotaLimit != null) {
      remainingCandidates.push(tenantQuotaLimit - tenantQuotaUsed);
    }
    quotaRemaining =
      remainingCandidates.length > 0 ? Math.min(...remainingCandidates) : null;
  }

  $: {
    if (quotaRemaining != null) {
      const totalUploadSize = files.reduce((total, file) => total + file.size, 0);
      quotaValidationError =
        quotaRemaining <= 0 || totalUploadSize > quotaRemaining
          ? {
              kind: "max_total_size",
              message: m.quota_limit_reached()
            }
          : null;
    } else {
      quotaValidationError = null;
    }
  }

  $: {
    validationErrors = [
      ...fileValidationErrors,
      ...(quotaValidationError ? [quotaValidationError] : [])
    ];
  }

  async function uploadBlobs() {
    if (validationErrors.length > 0) {
      return;
    }

    const duplicateFiles: string[] = [];
    const blobTitles = currentBlobs.flatMap((blob) => blob.metadata.title);
    files.forEach((file) => {
      if (blobTitles.includes(file.name)) {
        duplicateFiles.push(file.name);
      }
    });

    if (duplicateFiles.length > 0) {
      if (!confirm(m.duplicate_files_warning({ fileList: duplicateFiles.join("\\n- ") }))) {
        return;
      }
    }

    try {
      isUploading = true;
      queueUploads(collection.id, files);
      $showHeader = true;
      $showJobManagerPanel = true;
      $showDialog = false;
      isUploading = false;
      files = [];
      return;
    } catch (e) {
      alert(e);
    }
  }

  let showDialog: Dialog.OpenState;
</script>

<Dialog.Root
  bind:isOpen={showDialog}
  on:close={() => {
    files = [];
  }}
>
  <Dialog.Trigger asFragment let:trigger>
    <Button {disabled} variant="primary" is={trigger}>{m.upload_files()}</Button>
  </Dialog.Trigger>

  <Dialog.Content width="medium">
    <Dialog.Title>{m.upload_files()}</Dialog.Title>
    <Dialog.Description hidden></Dialog.Description>

    <Input.Files bind:files {acceptedMimeTypes}></Input.Files>

    {#if validationErrors.length > 0}
      <FileSizeValidationPanel errors={validationErrors} />
    {/if}

    <Dialog.Controls let:close>
      {#if files.length > 0}
        <Button
          on:click={() => {
            files = [];
          }}
          variant="destructive">{m.clear_list()}</Button
        >
        <div class="flex-grow"></div>
      {/if}
      <Button is={close}>{m.cancel()}</Button>
      <Button
        variant="primary"
        on:click={uploadBlobs}
        disabled={isUploading || files.length < 1 || validationErrors.length > 0}
      >
        {#if isUploading}{m.uploading()}{:else}{m.upload_files()}{/if}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
