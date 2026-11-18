import type { ConversationMessage } from "@eneo/eneo-js";
import { toolPresentation } from "@/features/chat/tool-presentation";

type Translate = (key: string, values?: Record<string, string | number>) => string;

export type WidgetToolStepStatus = "preparing" | "running" | "complete" | "failed" | "denied";

export type WidgetToolStep = {
  toolCallId: string | undefined;
  /** Human label of what the step did, e.g. "Aktuell tid" or "Sökte på webben efter X". */
  label: string;
  /** The label without its query, for the line that sums up several steps. */
  summary: string;
  /** The one argument worth showing, e.g. a timezone or a query; null when none reads well. */
  detail: string | null;
  serverName: string;
  /**
   * The external server to credit ("via TimeMCP"); null for Eneo's own tools
   * and capabilities, whose label already says where it looked.
   */
  via: string | null;
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
  is_internal?: boolean | null;
  is_bundled?: boolean | null;
};

/** Tool calls of a message: the streaming runtime list, else the persisted one. */
function messageToolCalls(message: ConversationMessage): ToolCall[] {
  const runtime = (message as Record<string, unknown>).mcp_tool_calls as ToolCall[] | undefined;
  return runtime ?? (message.tool_calls as ToolCall[] | undefined) ?? [];
}

const CAPABILITY_PURPOSES = new Set([
  "web_search",
  "image_generation",
  "file_analysis",
  "charts",
  "file_creation",
  "compute"
]);
const OWN_SERVERS = new Set(["knowledge", "files", "image_generation", "skills"]);

/**
 * Whether a call renders as one of Eneo's own steps (localized label that
 * already carries the query) rather than an external tool: a capability
 * call whichever provider served it, or a call on one of Eneo's loopback
 * servers. The backend's `is_internal` flag keeps an external server named
 * "files" from borrowing the built-in labels.
 */
export function isBuiltinCall(call: Pick<ToolCall, "server_name" | "purpose" | "is_internal">) {
  if (call.purpose && CAPABILITY_PURPOSES.has(call.purpose)) return true;
  return call.is_internal !== false && OWN_SERVERS.has(call.server_name);
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

/** The signed-in chat's labels for a built-in call, through its metadata shape. */
function builtinLabels(
  call: ToolCall,
  t: Translate,
  done: boolean,
  args: Record<string, unknown> | undefined
) {
  return toolPresentation(
    {
      toolName: call.tool_name,
      input: args,
      providerMetadata: {
        eneo: {
          server_name: call.server_name,
          title: call.title ?? null,
          purpose: call.purpose ?? null,
          is_internal: call.is_internal ?? null,
          is_bundled: call.is_bundled ?? null
        }
      }
    },
    t,
    done
  );
}

/**
 * The steps a visitor sees for an answer's tool calls, in call order. Eneo's
 * own tools and capability calls keep their localized labels (which already
 * carry the query); external tools get their catalog title and one argument.
 */
export function widgetToolSteps(
  message: ConversationMessage,
  { streaming, working }: { streaming: boolean; working: boolean },
  t: Translate
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
    const builtin = isBuiltinCall(call);
    if (builtin) {
      const done = status === "complete";
      const presentation = builtinLabels(call, t, done, args);
      // The query is folded into the label; the summary line leaves it out.
      const withoutQuery = args ? { ...args } : undefined;
      delete withoutQuery?.query;
      delete withoutQuery?.q;
      const summary = builtinLabels(call, t, done, withoutQuery);
      return {
        toolCallId: call.tool_call_id ?? undefined,
        label: presentation.label,
        summary: summary.label,
        detail: null,
        serverName: presentation.server ?? call.server_name,
        via: null,
        status
      };
    }
    const label = humanizeToolName(call.tool_name, call.title);
    return {
      toolCallId: call.tool_call_id ?? undefined,
      label,
      summary: label,
      detail: argumentDetail(args),
      serverName: call.server_name,
      via: call.server_name,
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

/** The external servers to credit, in first-seen order. */
export function creditedServers(steps: WidgetToolStep[]): string[] {
  return [...new Set(steps.flatMap((step) => (step.via ? [step.via] : [])))];
}
