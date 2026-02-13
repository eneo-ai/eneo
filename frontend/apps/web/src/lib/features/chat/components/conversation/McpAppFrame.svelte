<script lang="ts">
  import { onDestroy } from "svelte";
  import { AppBridge, PostMessageTransport } from "@modelcontextprotocol/ext-apps/app-bridge";

  interface Props {
    resourceUri: string;
    mcpServerId: string;
    toolArguments?: Record<string, unknown>;
    toolResult?: string;
    toolResultMeta?: Record<string, unknown>;
  }

  let { resourceUri, mcpServerId, toolArguments, toolResult, toolResultMeta }: Props = $props();

  let iframeEl = $state<HTMLIFrameElement | null>(null);
  let bridge: AppBridge | null = null;
  let bridgeInitialized = $state(false);
  let toolResultSent = false;
  let iframeHeight = $state(400);

  const src = `/mcp-resource/${mcpServerId}/render?uri=${encodeURIComponent(resourceUri)}`;

  function sendResult() {
    if (!bridge || !toolResult || toolResultSent) return;
    const resultPayload: Record<string, unknown> = {
      content: [{ type: "text", text: toolResult }],
      isError: false
    };
    if (toolResultMeta) {
      resultPayload._meta = $state.snapshot(toolResultMeta);
    }
    bridge.sendToolResult(resultPayload as any);
    toolResultSent = true;
  }

  // Set up AppBridge as soon as the iframe element is available.
  // This must happen BEFORE the iframe content loads, because the
  // MCP App inside calls App.connect() on load and expects a host
  // to respond to its JSON-RPC initialization request.
  $effect(() => {
    if (!iframeEl?.contentWindow || bridge) return;

    const appBridge = new AppBridge(
      null,
      { name: "Eneo", version: "1.0.0" },
      {}
    );

    appBridge.onsizechange = ({ height }: { height?: number; width?: number }) => {
      if (height && height > 0) {
        iframeHeight = Math.min(height, 2000);
      }
    };

    appBridge.oninitialized = () => {
      bridgeInitialized = true;

      if (toolArguments) {
        appBridge.sendToolInput({ arguments: $state.snapshot(toolArguments) });
      }

      sendResult();
    };

    const transport = new PostMessageTransport(
      iframeEl.contentWindow,
      iframeEl.contentWindow
    );
    appBridge.connect(transport);

    bridge = appBridge;
  });

  // Send tool result when it arrives after bridge is already initialized
  $effect(() => {
    if (toolResult && bridgeInitialized && bridge) {
      sendResult();
    }
  });

  onDestroy(() => {
    if (bridge) {
      bridge.close();
      bridge = null;
    }
  });
</script>

<div class="mt-2 overflow-hidden rounded-lg border border-dimmer">
  <iframe
    bind:this={iframeEl}
    {src}
    sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
    title="MCP App"
    style:height="{iframeHeight}px"
    class="w-full border-0 transition-[height] duration-200"
  ></iframe>
</div>
