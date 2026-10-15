<!--
  The title of what the panel shows, with a line of detail beneath it. When
  the conversation has more to show the two are also the switcher: one button
  that opens the list of views and files, and a choice from it takes the panel.
-->
<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import { m } from "$lib/paraglide/messages";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import type { FilePreview } from "../FilePreview.svelte";
  import type { PanelContents } from "../panelContents";
  import PanelContentsList from "./PanelContentsList.svelte";

  let {
    title,
    detail,
    preview,
    contents
  }: {
    title: string;
    /** Plain text under the title, such as the file's type and size. */
    detail?: string;
    preview: FilePreview;
    /** Everything the panel can show; without it the title is only a title. */
    contents?: PanelContents;
  } = $props();

  const count = $derived(
    contents ? contents.views.length + contents.documents.length + contents.uploads.length : 0
  );

  let open = $state(false);
  let trigger = $state<HTMLElement | null>(null);
  // A choice can replace the header this title sits in, and the trigger with
  // it. The focus then goes to the panel, where the chosen content is.
  let panel: HTMLElement | null = null;

  function choose(show: () => void) {
    panel = trigger?.closest("aside") ?? null;
    open = false;
    show();
  }
</script>

{#if contents && count > 1}
  <Popover.Root bind:open>
    <h2 class="flex min-w-0">
      <Popover.Trigger bind:ref={trigger}>
        {#snippet child({ props })}
          <Button
            {...props}
            variant="ghost"
            class="hover:bg-hover-default aria-expanded:bg-hover-default -mx-2 -my-1 h-auto max-w-full min-w-0 flex-col items-start gap-0 px-2 py-1 text-left leading-tight"
            {title}
          >
            <span class="flex max-w-full min-w-0 items-center gap-1">
              <span class="truncate font-semibold">{title}</span>
              <span class="sr-only">{m.panel_switcher_hint()}</span>
              <ChevronDown class="text-muted-foreground size-3.5" aria-hidden="true" />
            </span>
            {#if detail}
              <span
                class="text-muted-foreground max-w-full truncate text-xs font-normal tabular-nums"
              >
                {detail}
              </span>
            {/if}
          </Button>
        {/snippet}
      </Popover.Trigger>
    </h2>
    <Popover.Content
      align="start"
      class="w-80 max-w-[calc(100vw-2rem)] gap-0 p-0"
      aria-label={m.panel_switcher_heading()}
      onCloseAutoFocus={(event) => {
        if (!panel) return;
        event.preventDefault();
        panel.focus();
        panel = null;
      }}
    >
      <PanelContentsList
        {preview}
        views={contents.views}
        documents={contents.documents}
        uploads={contents.uploads}
        onfile={(file) => choose(() => preview.open(file, trigger))}
        onview={(view) => choose(view.open)}
      />
    </Popover.Content>
  </Popover.Root>
{:else}
  <h2 class="truncate text-sm font-semibold" {title}>{title}</h2>
  {#if detail}
    <p class="text-muted-foreground truncate text-xs tabular-nums">{detail}</p>
  {/if}
{/if}
