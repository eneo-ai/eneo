<script lang="ts">
  import "../../../../app.css";
  import PanelBackButton from "./PanelBackButton.svelte";
  import { m } from "$lib/paraglide/messages";
  import type { FilePreview } from "../FilePreview.svelte";
  import type { PanelContents } from "../panelContents";
  import FilePreviewLayout from "./FilePreviewLayout.svelte";

  let { preview, contents }: { preview: FilePreview; contents: PanelContents } = $props();
  let activeView = $state<string | null>(null);
  const items = $derived({
    ...contents,
    views: contents.views.map((view) => ({
      ...view,
      open: () => {
        activeView = view.title;
      }
    }))
  });
</script>

{#snippet viewPanel(onoverview: (() => void) | undefined)}
  {#if onoverview}<PanelBackButton onclick={onoverview} />{/if}
  <p>{activeView}</p>
  <button
    onclick={() => {
      activeView = null;
    }}>{m.close()}</button
  >
{/snippet}

<div style="width: 100vw; height: 600px">
  <FilePreviewLayout
    {preview}
    contents={items}
    occupant={{
      shown: activeView !== null,
      label: m.mcp_app_view_title(),
      close: () => {
        activeView = null;
      },
      panel: viewPanel
    }}
  >
    <div></div>
  </FilePreviewLayout>
</div>
