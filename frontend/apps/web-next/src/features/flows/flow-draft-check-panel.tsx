"use client";

import { Button } from "@astryxdesign/core/Button";
import { DropdownMenu } from "@astryxdesign/core/DropdownMenu";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Heading, Text } from "@astryxdesign/core/Text";
import { useQueries, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { Lightbulb } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useRef } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { useFocusRescue } from "@/lib/focus-rescue";
import {
  classificationPreviewQueryOptions,
  flowAssistantQueryOptions,
  toolOptionsQueryOptions
} from "./editor/editor-api";
import {
  optionToken,
  removedReads,
  repairedBindings,
  repairOptions,
  type RemovedRead
} from "./editor/reference-repair";
import { savedFlowPreviewRequest } from "./editor/step-draft";
import {
  chainIssueText,
  outputModeIssueText,
  stepLabel as stepNumberLabel
} from "./editor/step-labels";
import { stepUsesModel } from "./editor/step-rules";
import { toolRefusalText } from "./editor/step-tool-fields";
import type {
  ClassificationPreview,
  FlowAssistant,
  JsonObject,
  ToolOptions
} from "./editor/step-types";
import type { MaterialOption } from "./editor/step-variables";
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
import { showSuggestionsSummary } from "./flow-suggestions-section";
import {
  flowSuggestionsQueryOptions,
  suggestionCount,
  suggestionsOnPage
} from "./flow-suggestions";

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

function optionLabel(option: MaterialOption, t: Translate): string {
  const step = stepNumberLabel(option.stepOrder, option.stepName, t);
  return option.fieldPath
    ? t("flow_editor_tools_repair_option_field", { step, field: option.fieldPath })
    : step;
}

/**
 * One read of a removed step in a step's underlag, with what can take its
 * place: choosing one saves the step with it (the reference editor's repair).
 */
function RemovedReadRepair({
  flow,
  step,
  read,
  onRepair
}: {
  flow: FlowPublic;
  step: FlowStep;
  read: RemovedRead;
  onRepair: (step: FlowStep, inputBindings: JsonObject | null) => void;
}) {
  const t = useTranslations();
  const options = repairOptions(flow, step, read);
  const token = `{{${read.token}}}`;
  return (
    <div className="flex flex-col items-start gap-1">
      <Text size="sm" as="p" display="block" className="m-0 break-all">
        {t("flow_editor_tools_repair_from", { token })}
      </Text>
      {options.length > 0 ? (
        <DropdownMenu
          placement="below"
          alignment="start"
          button={{
            label: t("flow_editor_tools_repair_choose"),
            "aria-label": t("flow_editor_tools_repair_choose_named", {
              token,
              step: stepLabel(step, t)
            }),
            size: "sm",
            variant: "secondary"
          }}
          items={options.map((option) => ({
            id: option.key,
            label: optionLabel(option, t),
            description: `{{${optionToken(option)}}}`,
            onClick: () => {
              const bindings = repairedBindings(step, read, option);
              if (bindings) onRepair(step, bindings);
            }
          }))}
        />
      ) : (
        <Text type="supporting" size="sm" as="p" display="block" className="m-0">
          {t("flow_editor_tools_repair_none")}
        </Text>
      )}
    </div>
  );
}

/**
 * "Före publicering": what would stop the draft from being published, per
 * step, worked out again whenever the draft changes. Each step's problems
 * link to the step in the editor; the flow's own (no steps, no transcription
 * model) say where they are fixed. A read of a removed step in a step's
 * underlag can be replaced here in one choice (`onRepair` saves it). The
 * core's suggestions are not listed here, they sit on the step cards: while
 * the draft has some, one line says how many (the dismissed ones not
 * counted), and its button brings the summary above the step list into view
 * and puts focus on it. They never block or delay publishing.
 */
export function FlowDraftCheck({
  flow,
  suggestionRuns = 0,
  speakerServices,
  onOpenStep,
  onRepair
}: {
  flow: FlowPublic;
  /**
   * The runs the step list's suggestions are measured over; 0 for the
   * definition alone. The line reads the step list's answer, never one of
   * its own.
   */
  suggestionRuns?: number;
  speakerServices: readonly SpeakerServiceLink[];
  onOpenStep: (step: FlowStep) => void;
  /** Saves the step's repaired underlag; resolves to whether it was saved. */
  onRepair?: (step: FlowStep, inputBindings: JsonObject | null) => Promise<boolean>;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const rescue = useFocusRescue();
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
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
  const suggestions = useQuery(
    flowSuggestionsQueryOptions(flow.id, flow.draft_revision, suggestionRuns)
  );
  const suggested = suggestionCount(suggestionsOnPage(suggestions.data?.items, flow.steps));

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

  async function repair(step: FlowStep, inputBindings: JsonObject | null) {
    if (!onRepair) return;
    // The repaired read leaves the list with its menu: focus goes to the heading.
    if (await onRepair(step, inputBindings)) rescue(() => headingRef.current);
  }

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Heading
          level={2}
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          weight="semibold"
          className="focus-visible:outline-ring rounded-ax-inner text-lg focus-visible:outline-2 focus-visible:outline-offset-2"
        >
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
        <Banner
          status={unchecked ? "warning" : "success"}
          title={
            unchecked ? t("flow_editor_tools_check_incomplete") : t("flow_editor_tools_check_clean")
          }
          description={t("flow_editor_tools_check_clean_description")}
          collapsible={false}
        />
      ) : (
        <Banner
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
                  {onRepair && problems.some((problem) => problem.code === "deleted_reference")
                    ? removedReads(step, flow.steps).map((read) => (
                        <RemovedReadRepair
                          key={
                            read.location === "question"
                              ? `question:${read.token}`
                              : `ref:${read.index}:${read.token}`
                          }
                          flow={flow}
                          step={step}
                          read={read}
                          onRepair={(target, bindings) => void repair(target, bindings)}
                        />
                      ))
                    : null}
                </li>
              );
            })}
          </ul>
        </Banner>
      )}
      {suggested > 0 ? (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <Lightbulb aria-hidden="true" className="text-ax-text-secondary size-4 shrink-0" />
          <Text size="sm" as="p" display="block" className="m-0">
            {t("flow_suggestions_summary", { count: suggested })}
          </Text>
          <Button
            label={t("flow_suggestions_draft_check_show")}
            size="sm"
            variant="ghost"
            onClick={() => showSuggestionsSummary()}
          />
        </div>
      ) : null}
    </section>
  );
}
