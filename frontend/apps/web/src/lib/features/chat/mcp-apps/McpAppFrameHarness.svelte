<script lang="ts">
  import "../../../../app.css";
  import FilePreviewLayout from "../../file-preview/components/FilePreviewLayout.svelte";
  import type { FilePreview } from "../../file-preview/FilePreview.svelte";
  import McpAppFrame from "./McpAppFrame.svelte";
  import { initMcpAppPane } from "./McpAppPane.svelte";
  import type { McpAppCall } from "./mcpApps";
  const { call, width = 1000 }: { call: McpAppCall; width?: number } = $props();
  const preview = {
    shown: false,
    maximised: false,
    openedByItself: true,
    besideConversation: true,
    cover: null
  } as FilePreview;
  const pane = initMcpAppPane(preview);
</script>

<!-- eslint-disable-next-line eneo/no-hardcoded-text -- test harness control -->
<button onclick={() => pane.open(call.tool_call_id)}>Expand test app</button>
{#snippet panel()}
  <!-- eslint-disable-next-line eneo/no-hardcoded-text -- test harness control -->
  <button onclick={() => pane.close()}>Collapse test app</button>
  <div bind:this={pane.target} style="flex:1;min-height:0"></div>
{/snippet}
<div style={`width:${width}px;height:600px`}>
  <FilePreviewLayout
    {preview}
    occupant={{ shown: pane.shown, label: "Test app", close: () => pane.close(), panel }}
  >
    <McpAppFrame {call} live={false} />
  </FilePreviewLayout>
</div>
