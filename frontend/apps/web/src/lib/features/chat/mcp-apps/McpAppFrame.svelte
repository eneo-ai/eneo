<script lang="ts">
  import { untrack } from "svelte";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getThemeStore } from "$lib/core/theme";
  import { getChatService } from "../ChatService.svelte";
  import { toolsRunAutomatically } from "../toolApprovalPreference";
  import { McpAppBridge, type McpAppToolResult, type McpAppToolState } from "./bridge";
  import { hostContext } from "./hostContext";
  import { getMcpAppPane } from "./McpAppPane.svelte";
  import { getMcpAppUrlService } from "./McpAppUrlService.svelte";
  import {
    appViewTitle,
    buildAllowAttribute,
    hasResult,
    type McpAppCall,
    type McpAppDisplayMode
  } from "./mcpApps";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    call: McpAppCall;
    /** The call belongs to the answer being written right now. */
    live: boolean;
  };

  const { call, live }: Props = $props();

  const chat = getChatService();
  const urlService = getMcpAppUrlService();
  const pane = getMcpAppPane();

  const record = $derived(urlService.get(call.view.viewId));
  const allow = $derived(buildAllowAttribute(call.view.ui.permissions));
  // A view shown beside the conversation leaves a note where it stood.
  const movedToPane = $derived(pane?.callId === call.tool_call_id);
  const displayMode = $derived<McpAppDisplayMode>(movedToPane ? "fullscreen" : "inline");
  let panelRect = $state<{ top: number; left: number; width: number; height: number } | null>(null);
  $effect(() => {
    const target = movedToPane ? pane?.target : null;
    if (!target) {
      panelRect = null;
      return;
    }
    const measure = () => {
      const { top, left, width, height } = target.getBoundingClientRect();
      panelRect = { top, left, width, height };
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(target);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  });

  // What the view is told about its call: the arguments while the model
  // writes them, the finished arguments, and that the tool has returned.
  const tool = $derived<McpAppToolState>({
    partialInput: live ? chat.partialInputOf(call.tool_call_id) : undefined,
    input: call.arguments ?? undefined,
    resultReady: hasResult(call, live)
  });

  // A view takes the room it asks for. One shown with the answer being
  // written starts with none, so a view with nothing to show never flickers
  // into the answer; an earlier answer's view holds its place until it loads.
  const UNSIZED_HEIGHT = 320;
  const SIZE_WAIT_MS = 1500;
  let frameHeight = $state(untrack(() => (live ? 0 : UNSIZED_HEIGHT)));
  let sized = false;
  let frame = $state<HTMLIFrameElement | null>(null);
  let bridge = $state.raw<McpAppBridge | null>(null);
  // SDK sizes describe the app viewport; Tailwind uses border-box sizing.
  const frameBorder = $derived(frameHeight > 0 && call.view.ui.prefersBorder !== false ? 2 : 0);
  const frameStyle = $derived(
    movedToPane
      ? panelRect
        ? `position:fixed;z-index:30;top:${panelRect.top}px;left:${panelRect.left}px;width:${panelRect.width}px;height:${panelRect.height}px`
        : "visibility:hidden;position:fixed"
      : frameHeight === 0
        ? // Keep the bridge measurable and connected without adding a flex gap.
          "position:absolute;height:0;overflow:hidden"
        : `height:${frameHeight + frameBorder}px`
  );
  $effect(() => {
    bridge?.setDisplayMode(displayMode);
  });

  $effect(() => {
    bridge?.update(tool);
  });

  // A view shown in Eneo's colours follows them when the theme changes.
  const theme = getThemeStore();
  $effect(() => {
    void $theme;
    bridge?.contextChanged();
  });

  function requestDisplayMode(mode: McpAppDisplayMode): McpAppDisplayMode {
    if (!pane || mode === displayMode) return displayMode;
    // A view moves on the user's action in it. One that is merely on screen
    // cannot take the panel, except the view of the answer being written,
    // which may open it once unless the user has closed it during this answer.
    const acted = document.activeElement === frame;
    const opensWithItsAnswer = live && mode === "fullscreen" && !pane.dismissedThisAnswer;
    if (!acted && !opensWithItsAnswer) return displayMode;
    // Change only layout. The iframe and its SDK connection stay mounted.
    if (mode === "fullscreen") {
      pane.open(call.tool_call_id);
    } else {
      pane.close();
    }
    return mode;
  }

  // External code gets consent for each concrete call, never a server-wide
  // grant inherited from the model's automatic-tool preference.
  let asking = $state.raw<{
    name: string;
    args: Record<string, unknown>;
    decide: (allow: boolean) => void;
  } | null>(null);

  // A link is opened only when the reader, shown the whole address, says so.
  let link = $state.raw<{ url: string; decide: (open: boolean) => void } | null>(null);

  function openLink(url: string): Promise<boolean> {
    if (link) return Promise.resolve(false);
    return new Promise((resolve) => {
      link = {
        url,
        decide: (open) => {
          link = null;
          if (open) window.open(url, "_blank", "noopener,noreferrer");
          resolve(open);
        }
      };
    });
  }

  function offerMessage(text: string): boolean {
    // Only on the reader's action in the view: a view that is merely on
    // screen cannot write into the message box.
    if (document.activeElement !== frame) return false;
    chat.composerSuggestion = text;
    return true;
  }

  function permissionToRunTools(name: string, args: Record<string, unknown>): Promise<boolean> {
    if (call.is_bundled === true && toolsRunAutomatically()) return Promise.resolve(true);
    // Concurrent requests cannot share the approval of another call.
    if (asking) return Promise.resolve(false);
    return new Promise((resolve) => {
      asking = {
        name,
        args,
        decide: (allow) => {
          asking = null;
          resolve(allow);
        }
      };
    });
  }

  async function callTool(name: string, args: Record<string, unknown>): Promise<McpAppToolResult> {
    if (!(await permissionToRunTools(name, args))) {
      throw new Error("The user did not allow the tool call");
    }
    const result = await chat.callToolFromView({
      toolCallId: call.tool_call_id,
      viewId: call.view.viewId,
      name,
      arguments: args
    });
    return {
      content: (result.content ?? []).map((block) => ({ type: "text", text: block.text })),
      ...(result.structured_content ? { structuredContent: result.structured_content } : {}),
      ...(result.is_error ? { isError: true } : {})
    };
  }

  // The frame that has loaded the approved view. A frame can navigate itself
  // (a link in the view is enough) and would then hold a page nobody approved
  // in the same window; such a page is never given the bridge.
  let loadedFrame: HTMLIFrameElement | null = null;
  let leftApprovedView = $state(false);

  // Whether the loaded view says it can be shown beside the conversation.
  let enlargeable = $state(false);
  // Such a view, once it has something to show, is offered in the panel's
  // switcher, so the reader can bring it there without finding it in the chat.
  $effect(() => {
    if (!pane || !enlargeable || frameHeight === 0) return;
    const { offered } = pane;
    // The frame is keyed by its call, so the id is the same for its lifetime;
    // read untracked, a streamed update of the call does not withdraw the offer.
    const callId = untrack(() => call.tool_call_id);
    untrack(() => offered.add(callId));
    return () => offered.delete(callId);
  });

  function attachBridge(iframe: HTMLIFrameElement) {
    bridge?.destroy();
    enlargeable = false;
    if (loadedFrame === iframe) {
      bridge = null;
      leftApprovedView = true;
      return;
    }
    loadedFrame = iframe;
    bridge = new McpAppBridge({
      iframe,
      html: record?.html ?? "",
      permissions: call.view.ui.permissions?.clipboardWrite ? { clipboardWrite: {} } : undefined,
      displayMode,
      getToolResult: () => chat.getToolCallOutcome(call.tool_call_id),
      onSizeChanged: (height) => {
        sized = true;
        frameHeight = height;
      },
      onInitialized: (displayModes) => {
        enlargeable = displayModes.includes("fullscreen");
      },
      onRequestDisplayMode: pane ? requestDisplayMode : undefined,
      onCallTool: callTool,
      onOpenLink: openLink,
      onMessage: offerMessage,
      hostContext
    });
    const attached = bridge;
    // A view that never says its size is given room all the same.
    setTimeout(() => {
      if (!sized && bridge === attached) frameHeight = UNSIZED_HEIGHT;
    }, SIZE_WAIT_MS);
  }

  $effect(() => {
    return () => {
      asking?.decide(false);
      link?.decide(false);
      bridge?.destroy();
    };
  });
</script>

{#if movedToPane}
  <div
    class="border-default text-muted mt-2 flex items-center justify-between gap-3 rounded-lg border border-dashed px-3 py-2 text-xs"
    role="note"
  >
    <span>{m.mcp_app_view_beside()}</span>
    <Button variant="ghost" size="sm" onclick={() => pane?.close()}>
      {m.mcp_app_view_show_here()}
    </Button>
  </div>
{/if}

{#if record?.error !== undefined || leftApprovedView}
  <div
    class="border-default text-muted mt-2 rounded-lg border border-dashed px-3 py-2 text-xs"
    role="note"
  >
    {m.mcp_app_view_unavailable()}
  </div>
{:else if record?.url === undefined}
  <div
    class={[
      "border-default bg-tertiary animate-pulse rounded-lg border motion-reduce:animate-none",
      displayMode === "inline" ? "mt-2" : "m-4 flex-1",
      displayMode === "inline" && frameHeight === 0 && "hidden"
    ]}
    style={displayMode === "inline" ? `height: ${frameHeight}px` : undefined}
    aria-hidden="true"
  ></div>
{:else}
  <iframe
    bind:this={frame}
    src={record.url}
    title={m.mcp_app_view_title()}
    sandbox="allow-scripts allow-same-origin"
    {allow}
    referrerpolicy="no-referrer"
    loading={live ? "eager" : "lazy"}
    class={displayMode === "inline"
      ? [
          "w-full rounded-lg",
          // A view with nothing to show takes no room, border and margin included.
          frameHeight > 0 && "mt-2",
          frameHeight > 0 &&
            call.view.ui.prefersBorder !== false &&
            "border-default border shadow-sm"
        ]
      : "min-h-0 w-full flex-1"}
    style={`${frameStyle};${asking || link ? "visibility:hidden" : ""}`}
    onload={(event) => attachBridge(event.currentTarget as HTMLIFrameElement)}
  ></iframe>
{/if}

<AlertDialog.Root
  open={asking !== null}
  onOpenChange={(open) => {
    if (!open) asking?.decide(false);
  }}
>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.mcp_app_view_tool_permission_title()}</AlertDialog.Title>
      <AlertDialog.Description>
        {m.mcp_app_view_tool_permission_description({
          view: appViewTitle(call),
          tool: asking?.name ?? ""
        })}
      </AlertDialog.Description>
    </AlertDialog.Header>
    <pre
      class="bg-secondary max-h-64 overflow-auto rounded-md p-3 text-xs whitespace-pre-wrap break-all">{JSON.stringify(
        asking?.args ?? {},
        null,
        2
      )}</pre>
    <AlertDialog.Footer>
      <AlertDialog.Cancel onclick={() => asking?.decide(false)}>{m.tool_deny()}</AlertDialog.Cancel>
      <AlertDialog.Action onclick={() => asking?.decide(true)}>{m.tool_accept()}</AlertDialog.Action
      >
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>

<AlertDialog.Root
  open={link !== null}
  onOpenChange={(open) => {
    if (!open) link?.decide(false);
  }}
>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.mcp_app_view_open_link_title()}</AlertDialog.Title>
      <AlertDialog.Description>
        {m.mcp_app_view_open_link_description({
          view: appViewTitle(call)
        })}
      </AlertDialog.Description>
    </AlertDialog.Header>
    <p class="bg-secondary rounded-md px-3 py-2 font-mono text-xs break-all">{link?.url}</p>
    <AlertDialog.Footer>
      <AlertDialog.Cancel onclick={() => link?.decide(false)}>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action onclick={() => link?.decide(true)}>
        {m.mcp_app_view_open_link_confirm()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
