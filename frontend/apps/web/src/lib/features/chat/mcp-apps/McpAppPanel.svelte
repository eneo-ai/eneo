<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import PanelBackButton from "$lib/features/file-preview/components/PanelBackButton.svelte";
  import PanelTitle from "$lib/features/file-preview/components/PanelTitle.svelte";
  import type { FilePreview } from "$lib/features/file-preview/FilePreview.svelte";
  import type { PanelContents } from "$lib/features/file-preview/panelContents";
  import { m } from "$lib/paraglide/messages";
  import AppWindow from "@lucide/svelte/icons/app-window";
  import X from "@lucide/svelte/icons/x";
  import { getChatService } from "../ChatService.svelte";
  import type { McpAppPane } from "./McpAppPane.svelte";
  import { appViewTitle, findAppCall } from "./mcpApps";

  type Props = {
    pane: McpAppPane;
    /** The file preview this view shares the panel with. */
    preview: FilePreview;
    /** Everything the panel can show, for the switcher in the title. */
    contents?: PanelContents;
    onoverview?: () => void;
  };

  const { pane, preview, contents, onoverview }: Props = $props();

  const chat = getChatService();

  const found = $derived(
    pane.callId ? findAppCall(chat.currentConversation?.messages, pane.callId) : null
  );
  // The panel is headed by the tool the view belongs to; the frame's own
  // content is the server's and never names itself here.
  const title = $derived(appViewTitle(found?.call));
  // Closing a view that covers a file brings the file back; the button says so.
  const covered = $derived(preview.file?.name || preview.draft?.title || null);
  const closeLabel = $derived(
    covered ? m.mcp_app_view_close_to_file({ name: covered }) : m.close()
  );
</script>

{#if found}
  <header class="border-border flex min-h-16 shrink-0 items-center gap-3 border-b px-4 py-3">
    {#if onoverview}
      <PanelBackButton onclick={onoverview} />
    {/if}
    <span
      class="bg-accent-dimmer text-accent-stronger flex size-8 shrink-0 items-center justify-center rounded-md"
    >
      <AppWindow class="size-4" aria-hidden="true" />
    </span>
    <div class="flex min-w-0 flex-1 flex-col leading-tight">
      <PanelTitle {title} detail={m.mcp_app_view_title()} {preview} {contents} />
    </div>
    <Button
      variant="ghost"
      size="icon-sm"
      aria-label={closeLabel}
      title={closeLabel}
      onclick={() => pane.dismiss()}
    >
      <X aria-hidden="true" />
    </Button>
  </header>
  <!-- The original iframe stays mounted in the message. This is its layout anchor. -->
  <div bind:this={pane.target} class="min-h-0 flex-1"></div>
{/if}
