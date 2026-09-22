import type { ConversationMessage } from "@eneo/eneo-js";
import {
  internalToolDoneLabel,
  isBuiltinToolCall,
  serverDisplayName,
  toolDisplayName
} from "$lib/features/chat/internalToolLabels";

export type WidgetToolStepStatus = "preparing" | "running" | "complete" | "failed" | "denied";

export type WidgetToolStep = {
  toolCallId: string | undefined;
  /** Human label of what the step did, e.g. "Aktuell tid" or "Sökte på webben efter X". */
  label: string;
  /** The one argument worth showing, e.g. a timezone or a query; null when none reads well. */
  detail: string | null;
  serverName: string;
  status: WidgetToolStepStatus;
};

export type WidgetToolGroup = {
  label: string;
  serverName: string;
  steps: WidgetToolStep[];
};

type ToolCall = {
  server_name: string;
  tool_name: string;
  title?: string | null;
  arguments?: Record<string, unknown> | null;
  tool_call_id?: string | null;
  approved?: boolean | null;
  result_status?: string | null;
  purpose?: string | null;
};

/** Tool calls of a message: the streaming runtime list, else the persisted one. */
function messageToolCalls(message: ConversationMessage): ToolCall[] {
  const runtime = (message as Record<string, unknown>).mcp_tool_calls as ToolCall[] | undefined;
  return runtime ?? (message.tool_calls as ToolCall[] | undefined) ?? [];
}

/** "get_current_time" → "Get current time"; a server-provided title wins. */
export function humanizeToolName(toolName: string, title?: string | null): string {
  if (title?.trim()) return title.trim();
  const words = toolName
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .split(/[_\-\s]+/)
    .filter(Boolean);
  const text = words.join(" ").toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const DETAIL_KEYS = [
  "query",
  "q",
  "search",
  "timezone",
  "location",
  "url",
  "path",
  "name",
  "title",
  "id"
];
const DETAIL_MAX = 48;

/** The most telling string argument of a call, shortened for a chip. */
export function argumentDetail(args: Record<string, unknown> | null | undefined): string | null {
  if (!args) return null;
  const candidates = [...DETAIL_KEYS.map((key) => args[key]), ...Object.values(args)].filter(
    (value): value is string => typeof value === "string" && value.trim().length > 0
  );
  const value = candidates[0]?.trim();
  if (!value) return null;
  return value.length > DETAIL_MAX ? `${value.slice(0, DETAIL_MAX - 1)}…` : value;
}

/**
 * The steps a visitor sees for an answer's tool calls, in call order. Eneo's
 * own tools and capability calls keep their localized labels (which already
 * carry the query); external tools get their catalog title and one argument.
 */
export function widgetToolSteps(
  message: ConversationMessage,
  { streaming, working }: { streaming: boolean; working: boolean }
): WidgetToolStep[] {
  const calls = messageToolCalls(message);
  return calls.map((call, index) => {
    const denied =
      call.approved === false ||
      call.result_status === "denied" ||
      call.result_status === "timeout_denied";
    const last = index === calls.length - 1;
    // A call still "pending" after the stream ended never ran.
    const status: WidgetToolStepStatus = denied
      ? "denied"
      : call.result_status === "failed"
        ? "failed"
        : call.result_status === "pending"
          ? streaming
            ? "preparing"
            : "failed"
          : (call.result_status === "approved" && streaming) || (working && last)
            ? "running"
            : "complete";
    const args = call.arguments ?? undefined;
    const builtin = isBuiltinToolCall(call);
    const label = builtin
      ? ((status === "complete"
          ? internalToolDoneLabel(call.tool_name, call.server_name, args, call.purpose)
          : null) ??
        toolDisplayName(call.tool_name, call.server_name, call.title, args, call.purpose))
      : humanizeToolName(call.tool_name, call.title);
    return {
      toolCallId: call.tool_call_id ?? undefined,
      label,
      detail: builtin ? null : argumentDetail(args),
      serverName: serverDisplayName(call.server_name, call.purpose),
      status
    };
  });
}

/** Consecutive steps with the same label and server fold into one group. */
export function groupToolSteps(steps: WidgetToolStep[]): WidgetToolGroup[] {
  const groups: WidgetToolGroup[] = [];
  for (const step of steps) {
    const last = groups[groups.length - 1];
    if (last && last.label === step.label && last.serverName === step.serverName) {
      last.steps.push(step);
    } else {
      groups.push({ label: step.label, serverName: step.serverName, steps: [step] });
    }
  }
  return groups;
}

/** Distinct server labels, in first-seen order. */
export function stepServers(steps: WidgetToolStep[]): string[] {
  return [...new Set(steps.map((step) => step.serverName))];
}
