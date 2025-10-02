<script lang="ts">
  import UploadedFileIcon from "$lib/features/attachments/components/UploadedFileIcon.svelte";
  import { IconFileText } from "@intric/icons/file-text";
  import type { AppRun } from "@intric/intric-js";
  export let run: Pick<AppRun, "input">;
  import { m } from "$lib/paraglide/messages";
</script>

{#if run.input.text || run.input.files.length > 0}
  <div class="flex gap-2">
    {#if run.input.text}
      <div
        class="group-hover:bg-primary flex max-w-[40ch] gap-2 rounded-lg p-1 pr-2 backdrop-blur-sm group-hover:shadow"
      >
        <IconFileText class="min-w-6" /><span class="truncate">
          {m.input()}: {run.input.text}
        </span>
      </div>
    {/if}
    {#each run.input.files as file (file.id)}
      <div
        class="group-hover:bg-primary flex max-w-[40ch] gap-2 rounded-lg p-1 pr-2 backdrop-blur-sm group-hover:shadow"
      >
        <UploadedFileIcon {file} class="min-w-6" />
        <span class="truncate">
          {file.name}
        </span>
      </div>
    {/each}
  </div>
{:else}
  <div>{m.this_run_did_not_receive_any_inputs()}</div>
{/if}
