"use client";

import { Workflow } from "lucide-react";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import {
  messageToolCalls,
  type ToolCallRecord
} from "@/features/chat/side-panel/message-tool-calls";
import { useSidePanel } from "@/features/chat/side-panel/use-side-panel";
import type { EneoUIMessage } from "@/lib/chat/types";
import { cn } from "@/lib/utils";
import { FLOW_PANEL_ID } from "./flow-panel-store";
import { isFlowsCall } from "./flow-tool-calls";
import { flowQueryOptions } from "./flows";
import { useFlowPanel } from "./use-flow-panel";

/** The tools whose finished call gets a line under the answer, and its label key. */
const LINE_KEYS: Record<string, string> = {
  create_flow: "flow_line_created",
  update_flow: "flow_line_updated",
  publish_flow: "flow_line_published",
  delete_flow: "flow_line_deleted",
  run_flow: "flow_line_run_started",
  cancel_run: "flow_line_run_cancelled",
  review_run: "flow_line_run_reviewed"
};

function finished(call: ToolCallRecord): boolean {
  return call.state === "output-available" && call.resultStatus !== "failed";
}

function FlowLine({ call }: { call: ToolCallRecord }) {
  const t = useTranslations();
  const panel = useSidePanel();
  const store = useFlowPanel()!;
  const ref = store.refOf(call.toolCallId);
  const flowId = ref?.flowId ?? store.flowId;
  const flow = useQuery({ ...flowQueryOptions(flowId ?? ""), enabled: flowId !== null });
  const key = LINE_KEYS[call.toolName]!;
  const argumentName = typeof call.input?.name === "string" ? call.input.name : null;
  const name = argumentName ?? flow.data?.name ?? t("flow_line_unnamed");
  // The words around the name, split so the name can be set apart.
  const [before, after] = t(key, { name: "\u0000" }).split("\u0000");
  const shown = panel?.occupant.kind === "native" && panel.occupant.id === FLOW_PANEL_ID;

  return (
    <button
      type="button"
      aria-label={t("flow_line_open", { name })}
      aria-expanded={shown}
      onClick={() => {
        store.showCall(call.toolCallId);
        panel?.openNative(FLOW_PANEL_ID);
      }}
      className="text-ax-text-secondary hover:text-ax-text focus-visible:outline-ring rounded-ax-inner flex min-w-0 items-center gap-2 text-start text-sm focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11"
    >
      <span
        aria-hidden="true"
        className={cn(
          "rounded-ax-inner flex size-[22px] shrink-0 items-center justify-center",
          shown ? "bg-ax-purple text-ax-on-accent" : "bg-ax-purple-muted text-ax-purple"
        )}
      >
        <Workflow className="size-[13px]" />
      </span>
      <span className="truncate">
        {before}
        <span className="text-ax-text font-semibold">{name}</span>
        {after}
      </span>
    </button>
  );
}

/**
 * The lines under an answer for what its flows tool calls did ("Skapade
 * flödet Mötesprotokoll", "Startade körningen"); each opens the flow panel
 * on what the call was about. Reads of a flow or run get no line, and
 * outside a flow page there is nothing to open.
 */
export function FlowLines({ message }: { message: EneoUIMessage }) {
  const store = useFlowPanel();
  if (!store) return null;
  const calls = messageToolCalls(message).filter(
    (call) => isFlowsCall(call.part) && call.toolName in LINE_KEYS && finished(call)
  );
  if (calls.length === 0) return null;
  return (
    <div className="flex flex-col gap-2">
      {calls.map((call) => (
        <FlowLine key={call.toolCallId} call={call} />
      ))}
    </div>
  );
}
