import { buildAllowAttribute as sdkAllowAttribute } from "@modelcontextprotocol/ext-apps/app-bridge";
import type { EneoUIMessage } from "@/lib/chat/types";
import {
  messageToolCalls,
  type ToolCallRecord
} from "@/features/chat/side-panel/message-tool-calls";

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

/** A tool call that has a view to show. */
export type McpAppCall = ToolCallRecord & { view: McpAppView };

type Translate = (key: string) => string;

/** Built-in app titles follow the UI locale; external apps keep their own title. */
export function appViewTitle(call: McpAppCall | null | undefined, t: Translate): string {
  if (call?.isBundled && call.toolName === "query_table") return t("mcp_app_table_title");
  if (call?.isBundled && call.toolName === "create_chart") return t("mcp_app_chart_title");
  if (call?.isBundled && call.toolName === "run_javascript") return t("mcp_app_compute_title");
  return call?.title || call?.toolName || t("mcp_app_view_title");
}

/**
 * What a view is about, when its call says so in a `title` argument (a
 * chart's title, a table's caption). It tells two views of the same tool
 * apart in a list.
 */
export function appViewSubject(call: Pick<McpAppCall, "input">): string | null {
  return titleArgument(call.input);
}

/** The `title` a call names its result by (a chart's title, a table's caption), or null. */
export function titleArgument(args: Record<string, unknown> | null | undefined): string | null {
  const title = args?.title;
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
function wasStopped(call: ToolCallRecord): boolean {
  return (
    call.approved === false ||
    call.resultStatus === "failed" ||
    call.resultStatus === "denied" ||
    call.resultStatus === "timeout_denied"
  );
}

/**
 * Whether the tool's result can be handed to the view. A result is read from
 * the stored answer, and an answer is stored once it is complete, so a view
 * in an answer still being written waits for it.
 */
export function hasResult(call: Pick<ToolCallRecord, "resultStatus" | "state">, live: boolean) {
  if (live) return false;
  const status = call.resultStatus;
  // A call stored before statuses existed has no status and has long returned.
  return status == null || status === "succeeded" || status === "completed";
}

/** A bundled chart exported only as an input to another tool, such as a report. */
export function isChartDocumentAsset(
  call: Pick<ToolCallRecord, "isBundled" | "toolName" | "input">
) {
  return call.isBundled && call.toolName === "create_chart" && call.input?.display === "none";
}

/** The calls of a message whose tool has a view to show, in call order. */
export function appViewCalls(calls: readonly ToolCallRecord[]): McpAppCall[] {
  const shown: McpAppCall[] = [];
  for (const call of calls) {
    if (isChartDocumentAsset(call)) continue;
    // Explicit image exports render through the existing image block.
    if (
      call.isBundled &&
      call.toolName === "create_chart" &&
      (call.input?.format === "png" || call.input?.include_svg === true)
    )
      continue;
    const view = parseAppView(call.appView);
    if (!view || !call.toolCallId || wasStopped(call)) continue;
    shown.push({ ...call, view });
  }
  return shown;
}

/** The view-bearing calls of a message. */
export function messageAppViewCalls(message: EneoUIMessage): McpAppCall[] {
  return appViewCalls(messageToolCalls(message));
}

/** The call with a view to show that has this id, and whether it is in the newest message. */
export function findAppCall(
  messages: readonly EneoUIMessage[],
  toolCallId: string
): { call: McpAppCall; inLastMessage: boolean } | null {
  for (let index = messages.length - 1; index >= 0; index--) {
    const call = messageAppViewCalls(messages[index]!).find(
      (candidate) => candidate.toolCallId === toolCallId
    );
    if (call) return { call, inLastMessage: index === messages.length - 1 };
  }
  return null;
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
