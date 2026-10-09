<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import X from "@lucide/svelte/icons/x";
  import { tick } from "svelte";
  import ConversationPanelButton from "./ConversationPanelButton.svelte";
  import PanelContentsList from "./PanelContentsList.svelte";
  import * as Resizable from "$lib/components/ui/resizable/index.js";
  import * as Sheet from "$lib/components/ui/sheet/index.js";
  import { m } from "$lib/paraglide/messages";
  import type { Snippet } from "svelte";
  import type { DocumentExport, FilePreview } from "../FilePreview.svelte";
  import type { PanelContents } from "../panelContents";
  import type { PreviewFile } from "../previewKind";
  import FilePreviewPanel from "./FilePreviewPanel.svelte";

  type Props = {
    preview: FilePreview;
    /** Every version of the document a file belongs to, oldest first. */
    versionsOf?: (file: PreviewFile) => PreviewFile[];
    /** How a file is exported, for a document that can be; null for any other file. */
    exportOf?: (file: PreviewFile) => DocumentExport | null;
    /**
     * Something other than a file that takes the panel (an interactive tool
     * view). The panel shows one thing at a time; while this is shown it
     * covers the file, which is shown again when it closes.
     */
    occupant?: {
      shown: boolean;
      label: string;
      close: () => void;
      panel: Snippet<[onoverview: (() => void) | undefined]>;
    };
    /** Everything the panel can show, for the switcher in its title. */
    contents?: PanelContents;
    children: Snippet;
  };

  let { preview, versionsOf, exportOf, occupant, contents, children }: Props = $props();

  const panelId = $props.id();
  let overview = $state(false);
  let trigger = $state<HTMLButtonElement | null>(null);
  const hasContents = $derived(
    !!contents && contents.views.length + contents.documents.length + contents.uploads.length > 0
  );

  const occupied = $derived(occupant?.shown ?? false);
  const shown = $derived(preview.shown || occupied || (overview && hasContents));
  // A file may take the whole width; the conversation stays mounted behind it
  // and the split it returns to keeps its sizes.
  const maximised = $derived(preview.maximised && preview.shown && !occupied);
  const label = $derived(
    occupied && occupant
      ? occupant.label
      : preview.shown
        ? m.file_preview_title()
        : m.conversation_panel_title()
  );

  $effect(() => {
    // A file or view takes over the overview. Closing it then closes the panel.
    if (preview.shown || occupied || !hasContents) overview = false;
  });

  // A selected item can replace its own opener. Restore focus to the panel
  // control only when dismissal has left it on the page body.
  let wasShown = false;
  $effect(() => {
    const nowShown = shown;
    if (wasShown && !nowShown) {
      void tick().then(() => {
        if (document.activeElement === document.body) trigger?.focus();
      });
    }
    wasShown = nowShown;
  });

  async function choose(show: () => void) {
    overview = false;
    show();
    await tick();
    document.getElementById(panelId)?.focus();
  }

  async function showOverview() {
    occupant?.close();
    preview.close();
    overview = true;
    await tick();
    document.getElementById(panelId)?.focus();
  }

  function close() {
    if (occupied) occupant?.close();
    else if (preview.shown) preview.close();
    else overview = false;
  }

  // Below this width a split leaves neither side usable, so the preview opens
  // as a sheet over the content instead. Measured on the layout itself: the
  // space left for it depends on the navigation and any other open panel.
  const SPLIT_MIN_WIDTH = 720;
  let width = $state(0);
  const split = $derived(width >= SPLIT_MIN_WIDTH);

  $effect(() => {
    preview.besideConversation = split;
  });

  let panel = $state<HTMLElement | null>(null);

  $effect(() => {
    // Move focus into the panel when it opens so keyboard users land where
    // the new content is; closing hands it back to the chip that opened it.
    // A panel that opened by itself leaves the focus where the reader has it.
    if (!preview.openedByItself) panel?.focus();
  });

  function onDocumentKeydown(event: KeyboardEvent) {
    // Mirror dialog dismissal: Escape closes the panel when focus is inside
    // it. Open popovers and menus consume Escape first and prevent default.
    if (event.key !== "Escape" || event.defaultPrevented) return;
    if (!panel?.contains(document.activeElement)) return;
    event.preventDefault();
    // Escape steps back: out of the maximised panel first, then out of the panel.
    if (maximised) preview.maximised = false;
    else close();
  }
</script>

{#snippet content()}
  {#if !occupied && !preview.shown && overview && contents}
    <header class="border-border flex min-h-16 shrink-0 items-center gap-3 border-b px-4 py-3">
      <h2 class="flex min-h-8 min-w-0 flex-1 items-center text-sm font-semibold">
        {m.conversation_panel_title()}
      </h2>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label={m.conversation_panel_close()}
        title={m.conversation_panel_close()}
        onclick={close}
      >
        <X aria-hidden="true" />
      </Button>
    </header>
    <div class="min-h-0 flex-1 overflow-y-auto p-2">
      <PanelContentsList
        {preview}
        {...contents}
        fullHeight
        onfile={(file) => choose(() => preview.open(file, trigger))}
        onview={(view) => choose(view.open)}
      />
    </div>
  {/if}
  {#if occupied && occupant}
    {@render occupant.panel(hasContents ? showOverview : undefined)}
  {/if}
  {#if preview.shown}
    <!-- A covered file stays mounted, so it is as the reader left it (the
         place in it, the sheet on show) when the cover goes. -->
    <div
      class={["flex min-h-0 flex-col", occupied ? "invisible absolute inset-0" : "flex-1"]}
      inert={occupied}
      aria-hidden={occupied ? "true" : undefined}
    >
      <FilePreviewPanel
        {preview}
        {versionsOf}
        {exportOf}
        {contents}
        onoverview={hasContents ? showOverview : undefined}
        sheet={!split}
      />
    </div>
  {/if}
{/snippet}

<svelte:document onkeydown={onDocumentKeydown} />

<div class="relative h-full min-w-0" bind:clientWidth={width}>
  <Resizable.PaneGroup direction="horizontal" autoSaveId="file-preview-layout" class="min-w-0">
    <!-- Isolated, so nothing layered inside the conversation paints over a maximised panel. -->
    <Resizable.Pane
      order={1}
      defaultSize={50}
      minSize={30}
      class={["relative min-w-0", !occupied && "isolate"]}
    >
      <div class="flex h-full min-h-0 flex-col">
        {#if hasContents}
          <!-- Kept mounted for focus restoration, but absent while the panel is open. -->
          <div class="shrink-0 px-4 pt-2 md:px-6" hidden={shown}>
            <div class="flex justify-end">
              <ConversationPanelButton
                {panelId}
                bind:ref={trigger}
                onopen={() => {
                  preview.openedByItself = false;
                  overview = true;
                }}
              />
            </div>
          </div>
        {/if}
        <div class="min-h-0 flex-1">
          {@render children()}
        </div>
      </div>
    </Resizable.Pane>
    {#if shown && split}
      <Resizable.Handle
        withHandle
        aria-label={m.file_preview_resize_handle()}
        class="hover:bg-border focus-visible:ring-ring w-1 transition-colors motion-reduce:transition-none"
      />
      <Resizable.Pane
        order={2}
        defaultSize={50}
        minSize={30}
        maxSize={70}
        class="flex min-w-0 flex-col"
      >
        <aside
          id={panelId}
          bind:this={panel}
          aria-label={label}
          tabindex="-1"
          class={[
            "bg-background flex min-h-0 flex-col focus-visible:outline-none",
            maximised ? "absolute inset-0 z-20" : "relative h-full"
          ]}
        >
          {@render content()}
        </aside>
      </Resizable.Pane>
    {/if}
  </Resizable.PaneGroup>
</div>

{#if !split && occupied}
  <!-- The app remains mounted in the conversation, so this is a non-modal
       panel: a dialog focus trap would exclude the visually expanded iframe. -->
  <aside
    id={panelId}
    bind:this={panel}
    aria-label={label}
    tabindex="-1"
    class="bg-background fixed inset-0 z-20 flex min-h-0 flex-col"
  >
    {@render content()}
  </aside>
{:else if !split}
  <Sheet.Root
    open={shown}
    onOpenChange={(open) => {
      if (!open) close();
    }}
  >
    <Sheet.Content
      id={panelId}
      aria-label={label}
      class="gap-0 p-0 data-[side=right]:w-full data-[side=right]:sm:max-w-[44rem]"
      showCloseButton={false}
    >
      {#if shown}
        {@render content()}
      {/if}
    </Sheet.Content>
  </Sheet.Root>
{/if}
