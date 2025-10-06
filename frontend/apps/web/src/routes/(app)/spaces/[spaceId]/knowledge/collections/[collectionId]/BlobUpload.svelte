<script lang="ts">
  import { getAppContext } from "$lib/core/AppContext";
  import { getJobManager } from "$lib/features/jobs/JobManager";
  import { type Group, type InfoBlob } from "@intric/intric-js";
  import { Button, Dialog, Input } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  const {
    limits,
    state: { showHeader }
  } = getAppContext();
  const acceptedMimeTypes = limits.info_blobs.formats.map((format) => format.mimetype);

  const {
    queueUploads,
    state: { showJobManagerPanel }
  } = getJobManager();
  export let collection: Group;
  export let currentBlobs: InfoBlob[];
  export let disabled = false;

  let files: File[] = [];
  let isUploading = false;

  async function uploadBlobs() {
    const duplicateFiles: string[] = [];
    const blobTitles = currentBlobs.flatMap((blob) => blob.metadata.title);
    files.forEach((file) => {
      if (blobTitles.includes(file.name)) {
        duplicateFiles.push(file.name);
      }
    });

    if (duplicateFiles.length > 0) {
      if (
        !confirm(
          m.duplicate_files_warning({ fileList: duplicateFiles.join("\\n- ") })
        )
      ) {
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

    <Input.Files 
      bind:files 
      {acceptedMimeTypes}
    ></Input.Files>

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
      <Button variant="primary" on:click={uploadBlobs} disabled={isUploading || files.length < 1}>
        {#if isUploading}{m.uploading()}{:else}{m.upload_files()}{/if}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
