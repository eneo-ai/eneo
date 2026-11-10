import { Button } from "@astryxdesign/core/Button";
import { DropdownMenu } from "@astryxdesign/core/DropdownMenu";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Spinner } from "@astryxdesign/core/Spinner";
import { Heading, Text } from "@astryxdesign/core/Text";
import { useQueries, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, Lightbulb } from "lucide-react";
import { useFormatter, useTranslations } from "use-intl";
import { useEffect, useId, useRef, type RefObject } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { useFocusRescue } from "@/lib/focus-rescue";
import {
  classificationPreviewQueryOptions,
  flowAssistantQueryOptions,
  templateInspectionQueryOptions,
  toolOptionsQueryOptions
} from "./editor/editor-api";
import {
  optionToken,
  removedReads,
  repairedBindings,
  repairOptions,
  type RemovedRead
} from "./editor/reference-repair";
import type { FieldAnchor } from "./editor/field-problems";
import { readTemplateFill } from "./editor/step-configs";
import { savedFlowPreviewRequest } from "./editor/step-draft";
import {
  chainIssueText,
  outputModeIssueText,
  readWarning,
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
  problemAnchor,
  problemCount,
  type DraftCheck,
  type DraftFacts,
  type FlowProblem,
  type StepProblem
} from "./flow-draft-check";
import type { TranscriptionResources } from "./flow-transcription";
import { showSuggestionsSummary } from "./flow-suggestions-section";
import {
  flowSuggestionsQueryOptions,
  suggestionCount,
  suggestionsOnPage
} from "./flow-suggestions";

type Translate = ReturnType<typeof useTranslations>;
type Format = ReturnType<typeof useFormatter>;

/** Where in its step a reference sits, as the check's sentence names it. */
function referenceSite(anchor: FieldAnchor): string {
  if (anchor === "prompt") return "prompt";
  if (anchor === "input_bindings") return "bindings";
  return anchor === "input_config.tool" ? "tool" : "http";
}

/**
 * A problem of a step as a sentence. `flow` names the steps a warning is
 * about; `fieldLabel` names a Word field as the editor shows it.
 */
function stepProblemText(
  problem: StepProblem,
  flow: FlowPublic,
  t: Translate,
  format: Format,
  fieldLabel: (name: string) => string
): string {
  switch (problem.code) {
    case "chain":
      return chainIssueText(problem.issue, t);
    case "output_mode":
      return outputModeIssueText(problem.issue, t);
    case "name_missing":
      return t("flow_step_editor_name_required");
    case "prompt_missing":
      return t("flow_step_editor_instruction_missing");
    case "http_url_missing":
      return t("flow_step_editor_http_url_missing");
    case "http_credential_missing":
      return t("flow_editor_tools_check_http_credential_missing");
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
    case "tool_arguments_invalid":
      return t("flow_editor_tools_check_tool_arguments_invalid", {
        count: problem.names.length,
        names: format.list(problem.names)
      });
    case "template_unbound":
      return t("flow_editor_tools_check_template_unbound", {
        count: problem.names.length,
        names: format.list(
          problem.names.map((name) =>
            t("flow_editor_tools_check_quoted", { text: fieldLabel(name) })
          )
        )
      });
    case "template_orphaned":
      return t("flow_editor_tools_check_template_orphaned");
    case "template_structured":
      return t("flow_editor_tools_check_template_structured");
    case "speaker_participants_missing":
      return t("flow_editor_tools_check_speaker_participants_missing");
    case "model_missing":
      return t("flow_editor_tools_check_model_missing");
    case "reference": {
      // What each read means comes with the sentence where the editor words it.
      const warnings = new Set(
        problem.reads.flatMap((read) => readWarning(read.meaning, flow, t) ?? [])
      );
      return [
        t("flow_editor_tools_check_reference", {
          site: referenceSite(problem.anchor),
          tokens: format.list(problem.reads.map((read) => `{{${read.token}}}`))
        }),
        ...warnings
      ].join(" ");
    }
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
    case "live_model_unavailable":
      return t("flow_editor_tools_check_live_model_unavailable");
  }
}

/** The settings field that fixes a flow problem, for the ones fixed in the flow's settings. */
export type SettingsField = "transcription_model" | "speaker_service" | "live_model";
const SETTINGS_FIELD: Partial<Record<FlowProblem["code"], SettingsField>> = {
  transcription_model_missing: "transcription_model",
  speaker_service_missing: "speaker_service",
  live_model_unavailable: "live_model"
};

/** The check's verdict; a clean check beside the core's refusal says the refusal stands. */
function resultSentence(check: DraftCheck, t: Translate, refused: boolean): string {
  const count = problemCount(check);
  if (count > 0) return t("flow_editor_tools_check_problems", { count });
  return refused ? t("flow_editor_tools_check_refused") : t("flow_editor_tools_check_clean");
}

/** What the core answered for the draft, as the query cache holds it now. */
function cachedFacts(
  queryClient: QueryClient,
  flow: FlowPublic,
  transcription: TranscriptionResources
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
    transcription
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
 * link to the step in the editor; the flow's own lead to where they are
 * fixed: the settings field (`onOpenSettings`). A flow without steps has no
 * check: the page shows its empty step list instead.
 * A clean draft is one quiet line, "Redo att publicera"; only problems get a
 * banner. While the page shows the core's refusal of a publish (`refused`),
 * the line says so instead: the core saw what the check cannot. The page is
 * told the problem count (`onProblemCount`) and can put
 * focus on the heading (`headingRef`). A read of a removed step in a step's
 * underlag can be replaced here in one choice (`onRepair` saves it). The
 * core's suggestions are not listed here, they sit on the step cards: while
 * the draft has some, one line says how many (the dismissed ones not
 * counted), and its button brings the summary above the step list into view
 * and puts focus on it. They never block or delay publishing.
 */
export function FlowDraftCheck({
  flow,
  suggestionRuns = 0,
  transcription,
  onOpenStep,
  onRepair,
  onOpenSettings,
  onProblemCount,
  headingRef: pageHeadingRef,
  refused = false
}: {
  flow: FlowPublic;
  /**
   * The runs the step list's suggestions are measured over; 0 for the
   * definition alone. The line reads the step list's answer, never one of
   * its own.
   */
  suggestionRuns?: number;
  /** The space's transcription models and services. */
  transcription: TranscriptionResources;
  /** Opens the step at the field that fixes its first problem (`anchor`), or at its top. */
  onOpenStep: (step: FlowStep, anchor: FieldAnchor | null) => void;
  /** Saves the step's repaired underlag; resolves to whether it was saved. */
  onRepair?: (step: FlowStep, inputBindings: JsonObject | null) => Promise<boolean>;
  /** Opens the flow's settings at the field that fixes a flow problem. */
  onOpenSettings?: (field: SettingsField) => void;
  /** Told the problem count, or null while the draft is being checked or could not be. */
  onProblemCount?: (count: number | null) => void;
  /** The heading, for the page to bring the check into view and focus (Publicera does). */
  headingRef?: RefObject<HTMLHeadingElement | null>;
  /** The page shows the core's refusal of a publish of this draft. */
  refused?: boolean;
}) {
  const t = useTranslations();
  const format = useFormatter();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const rescue = useFocusRescue();
  const headingId = useId();
  const ownHeadingRef = useRef<HTMLHeadingElement>(null);
  const headingRef = pageHeadingRef ?? ownHeadingRef;
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
  // A Word field is named as the editor shows it once its template was read
  // there; reading one here would start the template runtime for a label.
  const templateIds = [
    ...new Set(
      flow.steps.flatMap((step) =>
        step.output_mode === "template_fill"
          ? (readTemplateFill(step.output_config).templateAssetId ?? [])
          : []
      )
    )
  ];
  const inspections = useQueries({
    queries: templateIds.map((id) => ({
      ...templateInspectionQueryOptions(flow.id, id),
      enabled: false
    }))
  });
  const fieldLabel = (step: FlowStep) => (name: string) => {
    const index = templateIds.indexOf(readTemplateFill(step.output_config).templateAssetId ?? "");
    const placeholders = inspections[index]?.data?.placeholders ?? [];
    return placeholders.find((placeholder) => placeholder.name === name)?.label || name;
  };

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
    transcription
  });
  const count = problemCount(check);
  const reported = pending || unchecked ? null : count;
  useEffect(() => {
    onProblemCount?.(reported);
    return () => onProblemCount?.(null);
  }, [reported, onProblemCount]);

  async function recheck() {
    const results = await Promise.all([
      ...assistants.map((query) => query.refetch()),
      ...(hasTools ? [toolOptions.refetch()] : []),
      ...(flow.steps.length > 0 ? [preview.refetch()] : [])
    ]);
    announce(
      results.some((result) => result.isError)
        ? t("flow_editor_tools_check_incomplete")
        : resultSentence(
            checkDraft(flow, cachedFacts(queryClient, flow, transcription)),
            t,
            refused
          )
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
          variant="ghost"
          isLoading={pending}
          isInterruptible
          onClick={() => {
            if (!pending) void recheck();
          }}
        />
      </div>
      {pending || (count === 0 && !unchecked) ? (
        // One quiet line, the same while it checks, so what follows does not move when it lands.
        <div className="flex min-h-6 items-center gap-2">
          {pending ? (
            <Spinner size="md" aria-hidden="true" />
          ) : refused ? (
            <CircleAlert aria-hidden="true" className="text-ax-text-secondary size-4 shrink-0" />
          ) : (
            <CircleCheck aria-hidden="true" className="text-ax-success size-4 shrink-0" />
          )}
          <Text size="sm" as="p" display="block" className="m-0">
            {pending
              ? t("flow_editor_tools_check_running")
              : refused
                ? t("flow_editor_tools_check_refused")
                : t("flow_editor_tools_check_clean")}
          </Text>
        </div>
      ) : count === 0 ? (
        <Banner
          status="warning"
          title={t("flow_editor_tools_check_incomplete")}
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
            {check.flow.map((problem) => {
              const field = SETTINGS_FIELD[problem.code];
              const textId = `${headingId}-${problem.code}`;
              const fix =
                field && onOpenSettings
                  ? {
                      label: t("flow_editor_tools_check_open_settings"),
                      run: () => onOpenSettings(field)
                    }
                  : null;
              return (
                <li
                  key={problem.code}
                  className="flex flex-wrap items-center justify-between gap-2"
                >
                  <span id={textId} className="text-ax-text text-sm">
                    {flowProblemText(problem, t)}
                  </span>
                  {fix ? (
                    <Button
                      label={fix.label}
                      aria-describedby={textId}
                      size="sm"
                      variant="ghost"
                      onClick={fix.run}
                    />
                  ) : null}
                </li>
              );
            })}
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
                      onClick={() =>
                        onOpenStep(step, problems[0] ? problemAnchor(problems[0]) : null)
                      }
                    />
                  </div>
                  <ul className="text-ax-text m-0 flex list-disc flex-col gap-0.5 pl-5 text-sm">
                    {problems.map((problem, index) => (
                      <li key={`${problem.code}-${index}`} className="break-words">
                        {stepProblemText(problem, flow, t, format, fieldLabel(step))}
                      </li>
                    ))}
                  </ul>
                  {onRepair
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
