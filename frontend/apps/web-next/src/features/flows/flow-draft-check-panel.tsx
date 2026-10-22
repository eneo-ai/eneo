"use client";

import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Heading, Text } from "@astryxdesign/core/Text";
import { useQueries, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useId } from "react";
import { QuietBanner } from "@/components/astryx/banner";
import {
  classificationPreviewQueryOptions,
  flowAssistantQueryOptions,
  toolOptionsQueryOptions
} from "./editor/editor-api";
import { savedFlowPreviewRequest } from "./editor/step-draft";
import { chainIssueText, outputModeIssueText } from "./editor/step-labels";
import { stepUsesModel } from "./editor/step-rules";
import { toolRefusalText } from "./editor/step-tool-fields";
import type { ClassificationPreview, FlowAssistant, ToolOptions } from "./editor/step-types";
import type { FlowPublic, FlowStep } from "./flows-api";
import { stepLabel } from "./flow-labels";
import {
  checkDraft,
  problemCount,
  type DraftCheck,
  type DraftFacts,
  type FlowProblem,
  type StepProblem
} from "./flow-draft-check";
import type { SpeakerServiceLink } from "./flow-transcription";

type Translate = ReturnType<typeof useTranslations>;

function stepProblemText(problem: StepProblem, t: Translate): string {
  switch (problem.code) {
    case "chain":
      return chainIssueText(problem.issue, t);
    case "output_mode":
      return outputModeIssueText(problem.issue, t);
    case "name_missing":
      return t("flow_step_editor_name_required");
    case "http_url_missing":
      return t("flow_step_editor_http_url_missing");
    case "tool_missing":
      return t("flow_step_editor_tool_required");
    case "tool_unavailable":
      return t("flow_step_editor_tool_unavailable");
    case "tool_refused":
      return toolRefusalText(problem.refusal, t);
    case "tool_arguments_missing":
      return t("flow_editor_tools_check_tool_arguments_missing", {
        names: problem.names.join(", ")
      });
    case "template_missing":
      return t("flow_editor_tools_check_template_missing");
    case "template_unbound":
      return t("flow_editor_tools_check_template_unbound");
    case "template_orphaned":
      return t("flow_editor_tools_check_template_orphaned");
    case "template_structured":
      return t("flow_editor_tools_check_template_structured");
    case "speaker_participants_missing":
      return t("flow_editor_tools_check_speaker_participants_missing");
    case "model_missing":
      return t("flow_editor_tools_check_model_missing");
    case "deleted_reference":
      return t("flow_editor_tools_check_deleted_reference");
    case "classification": {
      const key = `flow_error_${problem.violation.code}`;
      return t.has(key) ? t(key) : problem.violation.message;
    }
  }
}

function flowProblemText(problem: FlowProblem, t: Translate): string {
  switch (problem.code) {
    case "no_steps":
      return t("flows_publish_needs_steps");
    case "transcription_model_missing":
      return t("flow_editor_tools_check_transcription_model_missing");
    case "speaker_service_missing":
      return t("flow_editor_tools_check_speaker_service_missing");
  }
}

function resultSentence(check: DraftCheck, t: Translate): string {
  const count = problemCount(check);
  return count === 0
    ? t("flow_editor_tools_check_clean")
    : t("flow_editor_tools_check_problems", { count });
}

/** What the core answered for the draft, as the query cache holds it now. */
function cachedFacts(
  queryClient: QueryClient,
  flow: FlowPublic,
  speakerServices: readonly SpeakerServiceLink[]
): DraftFacts {
  const assistants = new Map<string, FlowAssistant>();
  for (const step of flow.steps) {
    const data = queryClient.getQueryData<FlowAssistant>(
      flowAssistantQueryOptions(flow.id, step.assistant_id).queryKey
    );
    if (data) assistants.set(data.id, data);
  }
  return {
    assistants,
    toolOptions:
      queryClient.getQueryData<ToolOptions>(toolOptionsQueryOptions(flow.id).queryKey)?.items ??
      null,
    classification:
      queryClient.getQueryData<ClassificationPreview>(
        classificationPreviewQueryOptions(flow.id, savedFlowPreviewRequest(flow)).queryKey
      )?.steps ?? null,
    speakerServices
  };
}

/**
 * "Före publicering": what would stop the draft from being published, per
 * step, worked out again whenever the draft changes. Each step's problems
 * link to the step in the editor; the flow's own (no steps, no transcription
 * model) say where they are fixed.
 */
export function FlowDraftCheck({
  flow,
  speakerServices,
  onOpenStep
}: {
  flow: FlowPublic;
  speakerServices: readonly SpeakerServiceLink[];
  onOpenStep: (step: FlowStep) => void;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const headingId = useId();
  const modelSteps = flow.steps.filter((step) => stepUsesModel(step) && step.assistant_id);
  const assistants = useQueries({
    queries: modelSteps.map((step) => flowAssistantQueryOptions(flow.id, step.assistant_id))
  });
  const hasTools = flow.steps.some((step) => step.input_source === "tool");
  const toolOptions = useQuery({ ...toolOptionsQueryOptions(flow.id), enabled: hasTools });
  const preview = useQuery({
    ...classificationPreviewQueryOptions(flow.id, savedFlowPreviewRequest(flow)),
    enabled: flow.steps.length > 0
  });

  const pending =
    assistants.some((query) => query.isPending) ||
    (hasTools && toolOptions.isPending) ||
    (flow.steps.length > 0 && preview.isPending);
  const unchecked =
    assistants.some((query) => query.isError) ||
    (hasTools && toolOptions.isError) ||
    preview.isError;

  const check = checkDraft(flow, {
    assistants: new Map(
      assistants.flatMap((query) =>
        query.data ? [[query.data.id, query.data] as [string, FlowAssistant]] : []
      )
    ),
    toolOptions: toolOptions.data?.items ?? null,
    classification: preview.data?.steps ?? null,
    speakerServices
  });
  const count = problemCount(check);

  async function recheck() {
    const results = await Promise.all([
      ...assistants.map((query) => query.refetch()),
      ...(hasTools ? [toolOptions.refetch()] : []),
      ...(flow.steps.length > 0 ? [preview.refetch()] : [])
    ]);
    announce(
      results.some((result) => result.isError)
        ? t("flow_editor_tools_check_incomplete")
        : resultSentence(checkDraft(flow, cachedFacts(queryClient, flow, speakerServices)), t)
    );
  }

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Heading level={2} id={headingId} weight="semibold" className="text-lg">
          {t("flow_editor_tools_check_heading")}
        </Heading>
        <Button
          label={t("flow_editor_tools_check_again")}
          size="sm"
          isLoading={pending}
          isInterruptible
          onClick={() => {
            if (!pending) void recheck();
          }}
        />
      </div>
      {pending ? (
        <Text type="supporting" size="sm" as="p" display="block" className="m-0">
          {t("flow_editor_tools_check_running")}
        </Text>
      ) : count === 0 ? (
        <QuietBanner
          status={unchecked ? "warning" : "success"}
          title={
            unchecked ? t("flow_editor_tools_check_incomplete") : t("flow_editor_tools_check_clean")
          }
          description={t("flow_editor_tools_check_clean_description")}
          collapsible={false}
        />
      ) : (
        <QuietBanner
          status="warning"
          title={t("flow_editor_tools_check_problems", { count })}
          description={unchecked ? t("flow_editor_tools_check_incomplete") : undefined}
          collapsible={false}
        >
          <ul className="m-0 flex list-none flex-col gap-3 p-0">
            {check.flow.map((problem) => (
              <li key={problem.code} className="text-ax-text text-sm">
                {flowProblemText(problem, t)}
              </li>
            ))}
            {check.steps.map(({ step, problems }) => {
              const label = stepLabel(step, t);
              return (
                <li key={step.id ?? step.step_order} className="flex flex-col gap-1">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-ax-text text-sm font-semibold break-words">{label}</span>
                    <Button
                      label={t("flow_editor_tools_check_open_step")}
                      aria-label={t("flow_editor_tools_check_open_step_named", { step: label })}
                      size="sm"
                      variant="ghost"
                      onClick={() => onOpenStep(step)}
                    />
                  </div>
                  <ul className="text-ax-text m-0 flex list-disc flex-col gap-0.5 pl-5 text-sm">
                    {problems.map((problem, index) => (
                      <li key={`${problem.code}-${index}`}>{stepProblemText(problem, t)}</li>
                    ))}
                  </ul>
                </li>
              );
            })}
          </ul>
        </QuietBanner>
      )}
    </section>
  );
}
