<script lang="ts">
  import { IconTrash } from "@intric/icons/trash";
  import { IconUpload } from "@intric/icons/upload";
  import { IconDownload } from "@intric/icons/download";
  import { Button, Dialog, Spinner } from "@intric/ui";
  import { createEventDispatcher } from "svelte";
  import { writable } from "svelte/store";
  import * as m from "$lib/paraglide/messages";

  /** Icon URL for display - pass the full URL directly */
  export let iconUrl: string | null = null;
  export let uploading = false;
  export let error: string | null = null;

  const dispatch = createEventDispatcher<{
    upload: File;
    delete: void;
  }>();

  let showPreview = writable(false);

  const MAX_SIZE = 262144; // 256KB
  const ALLOWED_TYPES = ["image/png", "image/jpeg", "image/webp"];

  function handleFileSelect(event: Event) {
    const target = event.target as HTMLInputElement;
    const file = target.files?.[0];

    if (!file) return;

    // Validate file type
    if (!ALLOWED_TYPES.includes(file.type)) {
      error = m.avatar_invalid_type();
      return;
    }

    // Validate file size
    if (file.size > MAX_SIZE) {
      error = m.avatar_too_large();
      return;
    }

    error = null;
    dispatch("upload", file);

    // Reset input
    target.value = "";
  }

  function handleDelete() {
    dispatch("delete");
  }

  function downloadAvatar() {
    if (!iconUrl) return;

    const link = document.createElement("a");
    link.href = iconUrl;
    link.download = "icon";
    link.click();
  }

  function openPreview() {
    $showPreview = true;
  }
</script>

{#if iconUrl}
  <div class="border-default bg-primary hover:bg-hover-dimmer flex h-16 items-center gap-3 border-b px-4">
    <button
      on:click={openPreview}
      class="h-12 w-12 overflow-hidden rounded-lg transition-opacity hover:opacity-80"
      aria-label="View avatar"
    >
      <img src={iconUrl} alt="Avatar" class="h-full w-full object-cover" />
    </button>

    <div class="flex-grow">
      <p class="line-clamp-1 text-sm">{m.avatar_current()}</p>
    </div>

    <Button variant="destructive" padding="icon" on:click={handleDelete} disabled={uploading}>
      <IconTrash />
    </Button>
  </div>

  <Dialog.Root alert openController={showPreview}>
    <Dialog.Content width="medium">
      <Dialog.Title>Avatar</Dialog.Title>

      <Dialog.Section>
        <div class="flex justify-center p-4">
          <img src={iconUrl} alt="Avatar preview" class="max-h-96 rounded-lg" />
        </div>
      </Dialog.Section>

      <Dialog.Controls let:close>
        <Button is={close} variant="secondary">{m.close?.() || "Close"}</Button>
        <Button variant="primary" on:click={downloadAvatar}>
          <IconDownload />
          {m.download?.() || "Download"}
        </Button>
      </Dialog.Controls>
    </Dialog.Content>
  </Dialog.Root>
{:else if uploading}
  <div class="border-default bg-primary hover:bg-hover-dimmer flex h-16 w-full items-center gap-4 border-b px-4">
    <Spinner />
    <span class="text-secondary line-clamp-1 text-sm">{m.avatar_uploading()}</span>
  </div>
{:else}
  <label
    for="avatarInput"
    class="border-default hover:bg-hover-stronger flex h-12 w-full cursor-pointer items-center justify-center gap-2 rounded-lg border transition-colors"
  >
    <IconUpload />
    <span>{m.avatar_upload()}</span>
  </label>
{/if}

{#if error}
  <div class="border-default bg-primary flex h-16 items-center border-b px-4">
    <p class="text-destructive text-sm">{error}</p>
  </div>
{/if}

<input
  type="file"
  id="avatarInput"
  accept={ALLOWED_TYPES.join(",")}
  on:change={handleFileSelect}
  class="pointer-events-none absolute h-0 w-0 rounded-lg file:border-none file:bg-transparent file:text-transparent"
/>
