import { m } from "$lib/paraglide/messages";
import { buildAllowAttribute as sdkAllowAttribute } from "@modelcontextprotocol/ext-apps/app-bridge";

/** Where a view is shown: under its answer, or beside the conversation. */
export type McpAppDisplayMode = "inline" | "fullscreen";

/** The stored view of a tool, and the render policy it was approved with. */
export type McpAppView = {
  viewId: string;
  ui: {
    prefersBorder?: boolean;
    permissions?: Record<string, unknown>;
    csp?: Record<string, unknown>;
  };
};

/** A tool call as the conversation carries it, streamed or loaded from history. */
type ToolCall = {
  tool_call_id?: string | null;
  tool_name?: string | null;
  title?: string | null;
  arguments?: Record<string, unknown> | null;
  approved?: boolean | null;
  is_bundled?: boolean | null;
  result_status?: string | null;
  app_view?: unknown;
};

/** A tool call that has a view to show. */
export type McpAppCall = ToolCall & { tool_call_id: string; view: McpAppView };

/** Built-in app titles follow the UI locale; external apps keep their own title. */
export function appViewTitle(call: McpAppCall | null | undefined): string {
  if (call?.is_bundled === true && call.tool_name === "query_table") {
    return m.mcp_app_table_title();
  }
  if (call?.is_bundled === true && call.tool_name === "create_chart") {
    return m.mcp_app_chart_title();
  }
  return call?.title || call?.tool_name || m.mcp_app_view_title();
}

/**
 * What a view is about, when its call says so in a `title` argument (a
 * chart's title). It tells two views of the same tool apart in a list.
 */
export function appViewSubject(call: McpAppCall): string | null {
  const title = call.arguments?.title;
  return typeof title === "string" && title.trim() ? title.trim() : null;
}

/**
 * Defensive parse of the view named on a tool call (`{view_id, ui}`). It is
 * built by the host, but from a server's declaration: anything malformed
 * shows nothing rather than something surprising.
 */
export function parseAppView(appView: unknown): McpAppView | null {
  if (appView === null || typeof appView !== "object") return null;
  const viewId = (appView as Record<string, unknown>).view_id;
  if (typeof viewId !== "string" || viewId.length === 0) return null;
  const ui = (appView as Record<string, unknown>).ui;
  return {
    viewId,
    ui: ui !== null && typeof ui === "object" ? (ui as McpAppView["ui"]) : {}
  };
}

/** A call that was refused, or that failed, has nothing for its view to show. */
function wasStopped(call: ToolCall): boolean {
  return (
    call.approved === false ||
    call.result_status === "failed" ||
    call.result_status === "timeout_denied"
  );
}

/**
 * Whether the tool's result can be handed to the view. A result is read from
 * the stored answer, and an answer is stored once it is complete, so a view
 * in an answer still being written waits for it.
 */
export function hasResult(call: ToolCall, live: boolean): boolean {
  if (live) return false;
  const status = call.result_status;
  // A call stored before statuses existed has no status and has long returned.
  return status == null || status === "succeeded" || status === "completed";
}

type MessageWithToolCalls = {
  /** Tool calls of an answer loaded from history. */
  tool_calls?: ToolCall[] | null;
  /** Tool calls of the answer being streamed. */
  mcp_tool_calls?: ToolCall[] | null;
};

/** A message's tool calls, whether it is being streamed or came from history. */
export function toolCallsOf(message: object): ToolCall[] {
  const { mcp_tool_calls, tool_calls } = message as MessageWithToolCalls;
  return mcp_tool_calls ?? tool_calls ?? [];
}

/** The call with a view to show that has this id, and whether it is in the newest message. */
export function findAppCall(
  messages: object[] | undefined,
  toolCallId: string
): { call: McpAppCall; inLastMessage: boolean } | null {
  const all = messages ?? [];
  for (let index = all.length - 1; index >= 0; index--) {
    const call = appViewCalls(toolCallsOf(all[index])).find(
      (candidate) => candidate.tool_call_id === toolCallId
    );
    if (call) return { call, inLastMessage: index === all.length - 1 };
  }
  return null;
}

/** A bundled chart exported only as an input to another tool, such as a report. */
export function isChartDocumentAsset(call: ToolCall): boolean {
  return (
    call.is_bundled === true &&
    call.tool_name === "create_chart" &&
    call.arguments?.display === "none"
  );
}

/** The calls of a message whose tool has a view to show, in call order. */
export function appViewCalls(calls: ToolCall[] | null | undefined): McpAppCall[] {
  const shown: McpAppCall[] = [];
  for (const call of calls ?? []) {
    if (isChartDocumentAsset(call)) continue;
    // Explicit image exports render through the existing image block.
    if (
      call.is_bundled &&
      call.tool_name === "create_chart" &&
      (call.arguments?.format === "png" || call.arguments?.include_svg === true)
    )
      continue;
    const view = parseAppView(call.app_view);
    if (!view || !call.tool_call_id || wasStopped(call)) continue;
    shown.push({ ...call, tool_call_id: call.tool_call_id, view });
  }
  return shown;
}

/**
 * Map declared spec permissions onto the iframe `allow` attribute. Writing to
 * the clipboard is the only one granted: camera, microphone and geolocation
 * would hand a server's HTML the user's device without the user being asked.
 */
export function buildAllowAttribute(permissions: Record<string, unknown> | undefined): string {
  return sdkAllowAttribute(
    permissions && "clipboardWrite" in permissions ? { clipboardWrite: {} } : undefined
  );
}
