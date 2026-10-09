<script lang="ts">
  import { Markdown } from "$lib/components/markdown/index.js";

  import type { PreviewDraft } from "../FilePreview.svelte";
  import { m } from "$lib/paraglide/messages";

  /** The document so far; it grows while the assistant writes. */
  let { draft }: { draft: PreviewDraft } = $props();

  let scroller = $state<HTMLElement>();
  // The view keeps to the newest text until the reader scrolls up to read.
  let following = true;

  $effect(() => {
    void draft;
    if (following && scroller) scroller.scrollTop = scroller.scrollHeight;
  });

  function onscroll() {
    if (!scroller) return;
    following = scroller.scrollHeight - scroller.clientHeight - scroller.scrollTop < 80;
  }
</script>

<div bind:this={scroller} {onscroll} class="min-h-0 flex-1 overflow-auto">
  <p class="text-muted-foreground px-6 pt-4 text-sm">
    {draft.showingPreviousDraft ? m.file_preview_previous_draft() : m.file_preview_draft_notice()}
  </p>
  {#if draft.sheets?.length}
    <div class="space-y-6 p-6">
      {#each draft.sheets as sheet, index (index)}
        <section>
          <h3 class="mb-2 font-semibold">{sheet.name || m.file_preview_preparing()}</h3>
          {#if sheet.fromSource}
            <p class="text-muted-foreground text-sm" role="status">
              {m.file_preview_draft_source()}
            </p>
          {:else if sheet.columns.length}
            <div class="overflow-x-auto">
              <table class="w-full border-collapse text-left text-sm">
                <thead
                  ><tr
                    >{#each sheet.columns as column, i (i)}<th scope="col" class="border p-2"
                        >{column}</th
                      >{/each}</tr
                  ></thead
                >
                <tbody
                  >{#each sheet.rows as row, i (i)}<tr
                      >{#each row as cell, j (j)}<td class="border p-2">{cell}</td>{/each}</tr
                    >{/each}</tbody
                >
              </table>
            </div>
            {#if sheet.truncated}<p class="text-muted-foreground mt-2 text-sm">
                {m.file_preview_draft_rows_limited()}
              </p>{/if}
          {:else}
            <p class="text-muted-foreground text-sm" role="status">{m.file_preview_preparing()}</p>
          {/if}
        </section>
      {/each}
    </div>
  {:else if draft.text}
    <Markdown source={draft.text} breaks={false} class="mx-auto max-w-[72ch] p-6 text-base" />
  {:else}
    <p class="text-muted-foreground p-6 text-sm" role="status">{m.file_preview_preparing()}</p>
  {/if}
</div>
