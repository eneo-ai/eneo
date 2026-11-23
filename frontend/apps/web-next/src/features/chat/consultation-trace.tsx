import { Collapsible, CollapsibleGroup } from "@/components/astryx/collapsible";
import { VStack } from "@astryxdesign/core/Layout";
import { useId, useState } from "react";
import { useTranslations } from "use-intl";
import {
  CitationSourcesProvider,
  citationComponents,
  useCitationRemarkPlugins
} from "@/components/ai-elements/citation";
import { ANSWER_TEXT_CLASS, MessageResponse } from "@/components/ai-elements/message";
import { resolveInrefs } from "@/lib/chat/inref";
import { recordedToolPart } from "@/lib/chat/map-session";
import type { EneoDataParts, EneoUIMessage } from "@/lib/chat/types";
import { deriveActivity } from "./activity";
import { SourceList, sourceAnchorId } from "./activity-sources";
import { StepList } from "./activity-steps";
import { McpImageStrip } from "./message-parts";

type Consultation = EneoDataParts["consultation"];

const STATUS_LABEL = {
  running: "chat_reasoning_working",
  awaiting_approval: "consultation_approval",
  complete: "chat_tool_status_done",
  denied: "consultation_denied",
  timeout: "consultation_timeout",
  cancelled: "consultation_cancelled",
  incomplete: "consultation_incomplete",
  failed: "chat_tool_status_failed"
} as const satisfies Record<Consultation["status"], string>;

function inProgress(status: Consultation["status"]) {
  return status === "running" || status === "awaiting_approval";
}

function ConsultationDetails({
  step,
  streaming,
  sessionId
}: {
  step: Consultation;
  streaming: boolean;
  sessionId: string | null;
}) {
  const t = useTranslations();
  const sourcePrefix = useId();
  const tools = step.tool_calls ?? [];
  const parts: EneoUIMessage["parts"] = tools.map((tool) => {
    // A pending call in a finished consultation is shown as stopped by deriveActivity.
    const pending =
      (!tool.result_status && step.status !== "complete") ||
      ["pending", "approved", "deferred", "awaiting_approval"].includes(tool.result_status ?? "");
    return recordedToolPart(
      tool,
      tool.step_id,
      pending
        ? tool.approved || tool.result_status === "approved"
          ? "input-available"
          : "input-streaming"
        : undefined
    );
  });
  parts.push({ type: "text", text: step.answer });
  const references = (step.references ?? []).map((ref) => {
    // A provider may reuse a call ID. Keep ambiguous sources on the specialist's reply.
    const matching = tools.filter(
      (tool) => ref.tool_call_id && tool.tool_call_id === ref.tool_call_id
    );
    return { ...ref, tool_call_id: matching.length === 1 ? matching[0]!.step_id : null };
  });
  const activity = deriveActivity(
    { id: step.id, role: "assistant", parts, metadata: { mcpToolReferences: references } },
    { streaming: streaming && inProgress(step.status) }
  );
  const plugins = useCitationRemarkPlugins(activity.sources.length, sourcePrefix);
  const sources = activity.sources.map((source) => source.sourceId);

  return (
    <VStack gap={3} align="stretch" className="min-w-0 pb-2">
      <div>
        <p className="text-ax-text-secondary mb-1 text-xs font-medium">
          {t("consultation_question")}
        </p>
        <p className="wrap-anywhere whitespace-pre-wrap">{step.question}</p>
      </div>
      {tools.length > 0 && (
        <div role="group" aria-label={t("chat_tools")}>
          <StepList
            activity={{
              ...activity,
              steps: activity.steps.filter((item) => item.kind !== "answer")
            }}
            durations={null}
            sessionId={sessionId}
          />
        </div>
      )}
      {step.answer && (
        <div>
          <p className="text-ax-text-secondary mb-1 text-xs font-medium">
            {t("consultation_answer")}
          </p>
          <CitationSourcesProvider
            value={activity.sources}
            prefix={sourcePrefix}
            onOpenSource={(index) =>
              document.getElementById(sourceAnchorId(sourcePrefix, index + 1))?.focus()
            }
          >
            <MessageResponse
              className={ANSWER_TEXT_CLASS}
              components={citationComponents}
              remarkPlugins={plugins}
            >
              {resolveInrefs(step.answer, sources)}
            </MessageResponse>
          </CitationSourcesProvider>
        </div>
      )}
      {sources.length > 0 && <SourceList messageId={sourcePrefix} sources={activity.sources} />}
      <McpImageStrip references={references} />
    </VStack>
  );
}

/** Live v3 snapshots replace the part with the same ID. History restores that same part. */
export function ConsultationTrace({
  parts,
  streaming,
  sessionId
}: {
  parts: EneoUIMessage["parts"];
  streaming: boolean;
  sessionId: string | null;
}) {
  const t = useTranslations();
  const [expanded, setExpanded] = useState(false);
  const [openSteps, setOpenSteps] = useState<string[]>([]);
  const steps = parts
    .filter((part) => part.type === "data-consultation")
    .map((part) => part.data)
    .sort((a, b) => a.ordinal - b.ordinal);
  if (!steps.length) return null;
  const active = streaming ? steps.find((step) => inProgress(step.status)) : undefined;

  return (
    <>
      <p className={active ? "text-ax-text-secondary text-sm" : "sr-only"} role="status">
        {active && `${active.assistant_name} · ${t(STATUS_LABEL[active.status])}`}
      </p>
      <Collapsible
        isOpen={expanded}
        onOpenChange={setExpanded}
        chevronPosition="start"
        className="rounded-ax-container border-ax-border border px-3"
        trigger={
          <span className="flex min-h-8 flex-wrap items-center gap-2 text-sm font-medium pointer-coarse:min-h-11">
            {t("consultations_summary", {
              count: steps.length,
              assistants: new Set(steps.map((step) => step.assistant_id)).size
            })}
          </span>
        }
      >
        <CollapsibleGroup
          type="multiple"
          hasDividers
          density="compact"
          value={openSteps}
          onChange={(value) => setOpenSteps(Array.isArray(value) ? value : [value])}
        >
          {steps.map((step) => (
            <Collapsible
              key={step.id}
              value={step.id}
              trigger={
                <span className="flex min-h-8 flex-wrap items-center gap-2 text-sm font-medium pointer-coarse:min-h-11">
                  {step.ordinal}. {step.assistant_name}
                  <span className="text-ax-text-secondary font-normal">
                    {t(
                      (!streaming && inProgress(step.status)
                        ? STATUS_LABEL.incomplete
                        : STATUS_LABEL[step.status]) ?? STATUS_LABEL.incomplete
                    )}
                  </span>
                </span>
              }
            >
              {expanded && openSteps.includes(step.id) && (
                <ConsultationDetails step={step} streaming={streaming} sessionId={sessionId} />
              )}
            </Collapsible>
          ))}
        </CollapsibleGroup>
      </Collapsible>
    </>
  );
}
