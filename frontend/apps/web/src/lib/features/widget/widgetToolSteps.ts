import type { ConversationMessage } from "@eneo/eneo-js";
import {
  capabilityProviderDetail,
  internalToolDoneLabel,
  serverDisplayName,
  toolDisplayName
} from "$lib/features/chat/internalToolLabels";

export type WidgetToolStepStatus = "preparing" | "running" | "complete" | "failed" | "denied";

export type WidgetToolStep = {
  toolCallId: string | undefined;
  /** Present-tense label, e.g. "Söker på webben". */
  toolName: string;
  /** Past-tense label, e.g. "Sökte på webben". */
  doneLabel: string;
  serverName: string;
  detail: string | null;
  args: Record<string, unknown> | undefined;
  status: WidgetToolStepStatus;
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

/**
 * The steps a visitor sees for an answer's tool calls, in call order. Every
 * call renders as a slim step: visitors get no tool result viewer and no
 * approval prompts, so there is nothing a card would add.
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
    const toolName = toolDisplayName(
      call.tool_name,
      call.server_name,
      call.title,
      args,
      call.purpose
    );
    return {
      toolCallId: call.tool_call_id ?? undefined,
      toolName,
      doneLabel:
        internalToolDoneLabel(call.tool_name, call.server_name, args, call.purpose) ?? toolName,
      serverName: serverDisplayName(call.server_name, call.purpose),
      detail: capabilityProviderDetail(call),
      args,
      status
    };
  });
}

/** Distinct server labels of a run, in first-seen order. */
export function stepServers(steps: WidgetToolStep[]): string[] {
  return [...new Set(steps.map((step) => step.serverName))];
}
