<script lang="ts">
  import { onMount } from "svelte";
  import type { Group, InfoBlob } from "@eneo/eneo-js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { getAppContext } from "$lib/core/AppContext";
  import { getEneo } from "$lib/core/Eneo";
  import { toastError } from "$lib/core/errors";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import {
    unsupportedTypeError,
    type AttachmentValidationError
  } from "$lib/features/attachments/AttachmentManager";
  import FileDropzone, {
    type FileSelection
  } from "$lib/features/attachments/components/FileDropzone.svelte";
  import FileSizeValidationPanel from "$lib/features/attachments/components/FileSizeValidationPanel.svelte";
  import { acceptedFormatsFromLimits } from "$lib/features/attachments/getAttachmentRules";
  import { getJobManager } from "$lib/features/jobs/JobManager";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    collection: Group;
    currentBlobs: InfoBlob[];
    disabled?: boolean;
  };

  let { collection, currentBlobs, disabled = false }: Props = $props();

  const {
    limits,
    user,
    state: { showHeader }
  } = getAppContext();
  const formats = acceptedFormatsFromLimits(limits.info_blobs.formats);
  const formatLimitByType = new Map(formats.map((format) => [format.mimetype, format.maxSize]));

  const {
    queueUploads,
    state: { showJobManagerPanel }
  } = getJobManager();
  const eneo = getEneo();

  let open = $state(false);
  let files = $state<File[]>([]);
  let skippedFiles = $state<File[]>([]);
  let duplicateFileNames = $state<string[]>([]);
  let isUploading = $state(false);
  let tenantQuotaLimit = $state<number | null>(null);
  let tenantQuotaUsed = $state(0);

  onMount(async () => {
    try {
      const summary = await eneo.usage.storage.getSummary();
      tenantQuotaLimit = summary.limit ?? null;
      tenantQuotaUsed = summary.total_used ?? 0;
    } catch (error) {
      console.error("BlobUpload: Failed to load storage summary", error);
    }
  });

  const fileValidationErrors = $derived.by(() => {
    const errors: AttachmentValidationError[] = [];
    for (const file of files) {
      const limit = formatLimitByType.get(file.type);
      if (limit === undefined) {
        errors.push(unsupportedTypeError(file));
      } else if (file.size > limit) {
        errors.push({
          kind: "file_size",
          fileName: file.name,
          fileSizeBytes: file.size,
          maxSizeBytes: limit,
          message: m.file_too_large_detail({
            fileName: file.name,
            currentSize: formatBytes(file.size),
            maxSize: formatBytes(limit)
          })
        });
      }
    }
    return errors;
  });

  const quotaRemaining = $derived.by(() => {
    const candidates: number[] = [];
    if (user.quota_limit != null) {
      candidates.push(user.quota_limit - (user.quota_used ?? 0));
    }
    if (tenantQuotaLimit != null) {
      candidates.push(tenantQuotaLimit - tenantQuotaUsed);
    }
    return candidates.length > 0 ? Math.min(...candidates) : null;
  });

  const quotaValidationError = $derived.by((): AttachmentValidationError | null => {
    if (quotaRemaining == null) return null;
    const totalUploadSize = files.reduce((total, file) => total + file.size, 0);
    return quotaRemaining <= 0 || totalUploadSize > quotaRemaining
      ? { kind: "max_total_size", message: m.quota_limit_reached() }
      : null;
  });

  const validationErrors = $derived([
    ...fileValidationErrors,
    ...(quotaValidationError ? [quotaValidationError] : [])
  ]);

  const canUpload = $derived(!isUploading && files.length > 0 && validationErrors.length === 0);

  function resetSelection() {
    files = [];
    skippedFiles = [];
    duplicateFileNames = [];
  }

  function handleSelection({ rejected }: FileSelection) {
    skippedFiles = [...skippedFiles, ...rejected];
  }

  function requestUpload() {
    if (!canUpload) return;
    const existingTitles = new Set(currentBlobs.map((blob) => blob.metadata.title));
    const duplicates = files
      .filter((file) => existingTitles.has(file.name))
      .map((file) => file.name);
    if (duplicates.length > 0) {
      duplicateFileNames = duplicates;
      return;
    }
    uploadFiles();
  }

  function uploadFiles() {
    duplicateFileNames = [];
    try {
      isUploading = true;
      queueUploads(collection.id, [...files]);
      $showHeader = true;
      $showJobManagerPanel = true;
      open = false;
    } catch (error) {
      toastError(error);
    } finally {
      isUploading = false;
    }
  }
</script>

<Dialog.Root
  bind:open
  onOpenChange={(isOpen) => {
    if (!isOpen) resetSelection();
  }}
>
  <Dialog.Trigger>
    {#snippet child({ props })}
      <Button {...props} {disabled}>{m.upload_files()}</Button>
    {/snippet}
  </Dialog.Trigger>

  <Dialog.Content class="sm:max-w-2xl" closeLabel={m.close()}>
    <Dialog.Header>
      <Dialog.Title>{m.upload_files()}</Dialog.Title>
      <Dialog.Description>
        {m.upload_files_to_collection_description({ name: collection.name })}
      </Dialog.Description>
    </Dialog.Header>

    <FileDropzone
      bind:files
      {formats}
      disabled={isUploading}
      onselect={handleSelection}
      class="max-h-[60vh] overflow-y-auto"
    />

    {#if skippedFiles.length > 0}
      <Alert.Root>
        <Alert.Description>
          {m.upload_skipped_unsupported_files({
            fileList: skippedFiles.map((file) => file.name).join(", ")
          })}
        </Alert.Description>
      </Alert.Root>
    {/if}

    <FileSizeValidationPanel errors={validationErrors} />

    <Dialog.Footer>
      {#if files.length > 0}
        <Button variant="ghost" onclick={resetSelection} disabled={isUploading} class="sm:mr-auto">
          {m.clear_list()}
        </Button>
      {/if}
      <Dialog.Close>
        {#snippet child({ props })}
          <Button {...props} variant="outline">{m.cancel()}</Button>
        {/snippet}
      </Dialog.Close>
      <Button onclick={requestUpload} disabled={!canUpload}>
        {isUploading ? m.uploading() : m.upload_files()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<AlertDialog.Root
  open={duplicateFileNames.length > 0}
  onOpenChange={(isOpen) => {
    if (!isOpen) duplicateFileNames = [];
  }}
>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.duplicate_files_dialog_title()}</AlertDialog.Title>
      <AlertDialog.Description>{m.duplicate_files_dialog_description()}</AlertDialog.Description>
    </AlertDialog.Header>
    <ul class="list-disc pl-5 text-sm">
      {#each duplicateFileNames as fileName (fileName)}
        <li>{fileName}</li>
      {/each}
    </ul>
    <AlertDialog.Footer>
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action onclick={uploadFiles}>{m.replace_files()}</AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
