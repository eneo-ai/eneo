"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { List, ListItem } from "@astryxdesign/core/List";
import { Heading, Text } from "@astryxdesign/core/Text";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, RotateCcw, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useMemo, useState } from "react";
import { TextInput } from "@/components/astryx/text-input";
import { ClientTime } from "@/components/composites/client-time";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { ComposeForm } from "./editor/compose-form";
import { DocumentForm } from "./editor/document-form";
import { FunctionForm } from "./editor/function-form";
import { LlmForm } from "./editor/llm-form";
import { ReviewForm } from "./editor/review-form";
import { placeProblems } from "./editor/step-problems";
import { uniqueKey } from "./editor/step-keys";
import type { FieldProblems } from "./editor/step-fields";
import { TranscribeForm } from "./editor/transcribe-form";
import {
  changedFields,
  KIND_FIELDS,
  useStepDraft,
  type DraftField,
  type StepDraftState
} from "./editor/use-step-draft";
import { SectionHeading, StepGlyph } from "./flow-definition";
import { runStatusLabel, stepKindLabel } from "./flow-labels";
import { stepUsedBy } from "./flow-reads";
import { FlowStepNav } from "./flow-step-nav";
import { NO_NAMES, type FlowNames } from "./flow-step-summary";
import {
  definitionProblems,
  flowKeys,
  flowRevisionQueryOptions,
  flowRunQueryOptions,
  flowRunsQueryOptions,
  invalidateFlow,
  updateFlow
} from "./flows";
import {
  stepsOf,
  type FlowDefinition,
  type FlowFunctionPublic,
  type FlowPublic,
  type FlowStep,
  type StepKind
} from "./types";

type Translate = ReturnType<typeof useTranslations>;

const FIELD_LABEL_KEYS: Record<DraftField, string> = {
  name: "name",
  description: "flow_editor_description",
  prompt: "flow_section_prompt",
  input: "flow_param_input",
  model_id: "model",
  model_kwargs: "flow_model_settings",
  files_from: "flow_param_files",
  knowledge: "knowledge",
  output: "output",
  template: "flow_param_template",
  template_file_id: "flow_param_template_file",
  content: "flow_param_content",
  values: "flow_param_fields",
  format: "flow_param_format",
  title: "title",
  filename: "flow_param_filename",
  purpose: "flow_param_function",
  tool: "flow_editor_tool",
  arguments: "flow_param_arguments",
  mode: "flow_editor_review_mode",
  of: "flow_section_reviews",
  expires_after_seconds: "flow_param_time_limit",
  source: "flow_param_source",
  transcription_model_id: "model",
  language: "language",
  speaker_labels: "flow_param_speakers",
  max_speakers: "flow_editor_max_speakers",
  speaker_mapping: "flow_editor_participants_field"
};

/** The human name of a draft field ("Instruktion till modellen"). */
export function fieldLabel(field: DraftField, t: Translate): string {
  return t(FIELD_LABEL_KEYS[field]);
}

/** An empty step of a kind, to be filled in by hand; reads the step before it. */
export function emptyStep(kind: StepKind, previousKey: string | null): FlowStep {
  const base = { key: "", name: "", description: null };
  switch (kind) {
    case "llm":
      return { ...base, kind, prompt: "", input: "{{previous}}", output: { type: "text" } };
    case "compose":
      return { ...base, kind, template: "{{previous}}" };
    case "document":
      return { ...base, kind, format: "docx", content: "{{previous}}" };
    case "function":
      return { ...base, kind, purpose: "compute", tool: "", arguments: {} };
    case "review":
      return { ...base, kind, mode: "edit", of: previousKey };
    case "transcribe":
      return { ...base, kind, source: "", speaker_labels: false };
  }
}

/** What the form itself can tell is missing before a save is worth sending. */
function localProblems(step: FlowStep, t: Translate): FieldProblems {
  const problems: FieldProblems = {};
  if (!step.name.trim()) problems.name = t("flow_editor_required");
  if (step.kind === "llm" && !step.prompt.trim()) problems.prompt = t("flow_editor_required");
  if (step.kind === "compose" && !step.template.trim()) {
    problems.template = t("flow_editor_required");
  }
  if (step.kind === "document" && !step.template_file_id && !step.content?.trim()) {
    problems.content = t("flow_editor_required");
  }
  if (step.kind === "function" && !step.tool.trim()) problems.tool = t("flow_editor_required");
  if (step.kind === "transcribe" && !step.source) problems.source = t("flow_editor_required");
  return problems;
}

function StepForm({
  draft,
  definition,
  index,
  names,
  functions,
  problems
}: {
  draft: StepDraftState;
  definition: FlowDefinition;
  index: number;
  names: FlowNames;
  functions?: FlowFunctionPublic[];
  problems: FieldProblems;
}) {
  switch (draft.draft.step.kind) {
    case "llm":
      return <LlmForm draft={draft} definition={definition} problems={problems} />;
    case "compose":
      return <ComposeForm draft={draft} definition={definition} problems={problems} />;
    case "document":
      return (
        <DocumentForm draft={draft} definition={definition} names={names} problems={problems} />
      );
    case "function":
      return (
        <FunctionForm
          draft={draft}
          definition={definition}
          functions={functions}
          problems={problems}
        />
      );
    case "review":
      return <ReviewForm draft={draft} definition={definition} index={index} problems={problems} />;
    case "transcribe":
      return <TranscribeForm draft={draft} definition={definition} problems={problems} />;
  }
}

/** The assistant's last version of the step, with one restore per field that differs. */
function AssistantVersion({
  flow,
  step,
  draft
}: {
  flow: FlowPublic;
  step: FlowStep;
  draft: StepDraftState;
}) {
  const t = useTranslations();
  const origin = flow.step_origins?.find((entry) => entry.key === step.key) ?? null;
  const revision = origin?.assistant_revision ?? null;
  const query = useQuery({
    ...flowRevisionQueryOptions(flow.id, revision ?? 0),
    enabled: revision !== null
  });
  const theirs = query.data ? stepsOf(query.data.definition).find((s) => s.key === step.key) : null;
  const differing = theirs ? changedFields(draft.draft.step, theirs) : [];
  return (
    <section aria-labelledby="flow-editor-assistant" className="flex flex-col gap-2">
      <SectionHeading id="flow-editor-assistant">
        {t("flow_editor_assistant_version")}
      </SectionHeading>
      {origin === null ? (
        <Text type="supporting" size="sm">
          {t("flow_editor_assistant_none")}
        </Text>
      ) : revision === null ? (
        <Text type="supporting" size="sm">
          {origin.channel === "mcp"
            ? t("flow_editor_assistant_unchanged")
            : t("flow_editor_assistant_never")}
        </Text>
      ) : !theirs ? (
        <Text type="supporting" size="sm">
          {query.isPending ? t("loading") : t("flow_editor_assistant_gone")}
        </Text>
      ) : (
        <>
          <Text type="supporting" size="sm">
            {t("flow_history_revision", { revision })}
            {" · "}
            <ClientTime value={query.data!.created_at} format="date_time" />
          </Text>
          {theirs.kind === "llm" && differing.includes("prompt") && (
            <Card variant="muted" padding={3}>
              <Text
                type="body"
                size="sm"
                as="p"
                display="block"
                className="m-0 max-h-56 overflow-auto whitespace-pre-wrap"
              >
                {theirs.prompt}
              </Text>
            </Card>
          )}
          {differing.length === 0 ? (
            <Text type="supporting" size="sm">
              {t("flow_editor_assistant_same")}
            </Text>
          ) : (
            <div className="flex flex-wrap gap-1">
              {differing.map((field) => (
                <Button
                  key={field}
                  label={t("flow_editor_restore_field", { field: fieldLabel(field, t) })}
                  variant="ghost"
                  size="sm"
                  icon={<RotateCcw className="size-4" />}
                  onClick={() => draft.restoreFrom(field, theirs)}
                />
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}

/** The latest test run's result for this step, as a reminder of what it produced. */
function LastTestRun({
  flow,
  step,
  onOpenRun,
  disabled
}: {
  flow: FlowPublic;
  step: FlowStep;
  onOpenRun: (runId: string) => void;
  disabled: boolean;
}) {
  const t = useTranslations();
  const runs = useInfiniteQuery(flowRunsQueryOptions(flow.id));
  const latest = runs.data?.pages.flatMap((page) => page.items).find((run) => run.is_test) ?? null;
  const detail = useQuery({
    ...flowRunQueryOptions(flow.id, latest?.id ?? ""),
    enabled: latest !== null
  });
  const result = detail.data?.steps?.find((candidate) => candidate.step_id === step.id) ?? null;
  const output = result?.output_payload_json as Record<string, unknown> | null | undefined;
  const preview =
    output && typeof output.text === "string"
      ? output.text
      : output && output.value != null
        ? JSON.stringify(output.value)
        : null;
  return (
    <section aria-labelledby="flow-editor-last-run" className="flex flex-col gap-2">
      <SectionHeading id="flow-editor-last-run">{t("flow_editor_last_test_run")}</SectionHeading>
      {latest === null || result === null ? (
        <Text type="supporting" size="sm">
          {runs.isPending || detail.isPending ? t("loading") : t("flow_editor_last_test_run_none")}
        </Text>
      ) : (
        <>
          <Text type="supporting" size="sm">
            <ClientTime value={latest.created_at} format="date_time" />
            {" · "}
            {runStatusLabel(result.status, t)}
          </Text>
          {preview && (
            <Card variant="muted" padding={3}>
              <Text
                type="body"
                size="sm"
                as="p"
                display="block"
                className="m-0 max-h-40 overflow-auto whitespace-pre-wrap"
              >
                {preview.length > 600 ? `${preview.slice(0, 600)}…` : preview}
              </Text>
            </Card>
          )}
          <Button
            label={t("flow_editor_open_run")}
            variant="ghost"
            size="sm"
            isDisabled={disabled}
            onClick={() => onOpenRun(latest.id)}
            className="self-start"
          />
        </>
      )}
    </section>
  );
}

/** What else changes when this step does: the steps that read it. */
function AffectedSteps({ step, definition }: { step: FlowStep; definition: FlowDefinition }) {
  const t = useTranslations();
  const uses = step.key ? stepUsedBy(step.key, definition) : [];
  return (
    <section aria-labelledby="flow-editor-affects" className="flex flex-col gap-2">
      <SectionHeading id="flow-editor-affects">{t("flow_editor_affects")}</SectionHeading>
      {uses.length === 0 ? (
        <Text type="supporting" size="sm">
          {t("flow_used_by_none")}
        </Text>
      ) : (
        <List density="compact">
          {uses.map((use) => (
            <ListItem
              key={use.step.key}
              label={`${t("flow_ref_step", { index: use.index + 1 })} · ${use.step.name}`}
              description={
                use.via === "review" ? t("flow_used_by_review") : t("flow_editor_affects_reads")
              }
              startContent={<StepGlyph step={use.step} index={use.index} />}
            />
          ))}
        </List>
      )}
    </section>
  );
}

/**
 * The editor of one step, in edit mode: the form of its kind, a note for
 * the history, and a reference column (the assistant's version with
 * per-field restore, the steps it affects, its last test run). Saving
 * replaces the step by key in the whole definition and PATCHes the flow;
 * a new step is inserted at its position with a key made from its name.
 * The validator's problems come back to the fields they name.
 */
export function FlowStepEditor({
  flow,
  target,
  names = NO_NAMES,
  functions,
  wide,
  onSaved,
  onCancel,
  onOpenRun,
  onDeleted
}: {
  flow: FlowPublic;
  /** The step to edit, or a new one of a kind to insert at an index. */
  target: { step: FlowStep } | { kind: StepKind; index: number };
  names?: FlowNames;
  /** What the space can call, for a function step's form. */
  functions?: FlowFunctionPublic[];
  wide: boolean;
  /** The step was saved (its key, which a new step gets on save). */
  onSaved: (key: string) => void;
  onCancel: () => void;
  onOpenRun: (runId: string) => void;
  onDeleted: () => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const formId = useId();
  const { definition } = flow;
  const steps = stepsOf(definition);
  const isNew = !("step" in target);
  const index = isNew ? target.index : steps.findIndex((step) => step.key === target.step.key);
  const saved = useMemo<FlowStep>(
    () =>
      "step" in target
        ? target.step
        : emptyStep(target.kind, index > 0 ? (steps[index - 1]?.key ?? null) : null),
    // A new step's blank form is made once; the flow's steps may refetch meanwhile.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [target, index]
  );
  const draft = useStepDraft(saved);
  const [note, setNote] = useState("");
  const [serverProblems, setServerProblems] = useState<string[]>([]);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [showLocal, setShowLocal] = useState(false);
  const dirty = isNew || draft.dirty.length > 0;
  const step = draft.draft.step;

  const placed = placeProblems(serverProblems, step.key);
  const problems: FieldProblems = {
    ...(showLocal ? localProblems(draft.built ?? step, t) : {}),
    ...Object.fromEntries(placed.filter((p) => p.field).map((p) => [p.field, p.text]))
  };
  const general = placed.filter((p) => p.field === null).map((p) => p.text);

  const withStep = (next: FlowStep | null): FlowDefinition => ({
    ...definition,
    steps: isNew
      ? [...steps.slice(0, index), ...(next ? [next] : []), ...steps.slice(index)]
      : steps.flatMap((candidate) =>
          candidate.key === step.key ? (next ? [next] : []) : [candidate]
        )
  });

  const save = useMutation({
    mutationFn: (next: FlowStep) =>
      updateFlow(flow.id, { definition: withStep(next), note: note.trim() || null }),
    onSuccess: (updated, next) => {
      queryClient.setQueryData(flowKeys.flow(flow.id), updated);
      void invalidateFlow(queryClient, flow.id);
      toast.success(t("flow_editor_saved", { revision: updated.revision ?? 1 }));
      onSaved(next.key);
    },
    onError: (error) => {
      const list = definitionProblems(error);
      if (list) setServerProblems(list);
      else toastApiError(error, t);
    }
  });

  const remove = useMutation({
    mutationFn: () =>
      updateFlow(flow.id, {
        definition: withStep(null),
        note: t("flow_editor_delete_note", { name: step.name })
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(flowKeys.flow(flow.id), updated);
      void invalidateFlow(queryClient, flow.id);
      setConfirmDelete(false);
      toast.success(t("flow_editor_deleted", { name: step.name }));
      onDeleted();
    },
    onError: (error) => {
      setConfirmDelete(false);
      const list = definitionProblems(error);
      if (list) setServerProblems(list);
      else toastApiError(error, t);
    }
  });

  const submit = () => {
    if (save.isPending) return;
    setShowLocal(true);
    const built = draft.built;
    if (!built || Object.keys(localProblems(built, t)).length > 0) return;
    const next: FlowStep =
      isNew || !built.key
        ? {
            ...built,
            key: uniqueKey(
              built.name,
              steps.map((candidate) => candidate.key)
            )
          }
        : built;
    setServerProblems([]);
    save.mutate(next);
  };

  const readers = step.key ? stepUsedBy(step.key, definition) : [];
  const changedCount = isNew ? KIND_FIELDS[step.kind].length : draft.dirty.length;

  const reference = (
    <aside
      aria-label={t("flow_editor_reference")}
      className={cn("flex flex-col gap-6", wide && "@min-[1100px]:w-80 @min-[1100px]:shrink-0")}
    >
      {!isNew && <AssistantVersion flow={flow} step={saved} draft={draft} />}
      <AffectedSteps step={step} definition={definition} />
      {!isNew && <LastTestRun flow={flow} step={saved} onOpenRun={onOpenRun} disabled={dirty} />}
      <Text type="supporting" size="xsm" as="p" display="block" className="m-0 leading-snug">
        {t("flow_editor_saves_as", { revision: (flow.revision ?? 1) + 1 })}
      </Text>
    </aside>
  );

  const saveBar = (
    <div className="bg-ax-surface border-ax-border sticky bottom-0 flex flex-wrap items-center gap-3 border-t px-4 py-3">
      <div className="flex min-w-0 flex-1 flex-col">
        <Text type="body" size="sm" weight="semibold">
          {isNew
            ? t("flow_editor_new_step_position", { index: index + 1 })
            : t("flow_editor_changed_fields", { count: changedCount, index: index + 1 })}
        </Text>
        <Text type="supporting" size="xsm">
          {t("flow_editor_saves_as", { revision: (flow.revision ?? 1) + 1 })}
        </Text>
      </div>
      <Button label={t("cancel")} size="sm" onClick={onCancel} />
      <Button
        label={isNew ? t("flow_editor_add_step") : t("flow_editor_save_draft")}
        variant="primary"
        size="sm"
        type="submit"
        form={formId}
        icon={<Check className="size-4" />}
        isLoading={save.isPending}
        isInterruptible
        isDisabled={!dirty}
      />
    </div>
  );

  const main = (
    <form
      id={formId}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      className="flex min-h-0 flex-1 flex-col"
    >
      <div className={cn("flex min-w-0 flex-1 flex-col gap-6", wide ? "p-6" : "p-4")}>
        <header className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <Text type="supporting" size="sm">
              {isNew
                ? t("flow_editor_new_step_position", { index: index + 1 })
                : t("flow_editor_editing_step", { index: index + 1 })}
            </Text>
            <Badge
              variant={step.kind === "review" ? "orange" : "neutral"}
              label={stepKindLabel(step.kind, t)}
            />
          </div>
          <Heading level={2} className="m-0 text-lg leading-tight font-semibold">
            {step.name.trim() || t("flow_editor_unnamed_step")}
          </Heading>
        </header>
        {general.length > 0 && (
          <Card variant="red" padding={3}>
            <ul role="alert" className="m-0 flex list-disc flex-col gap-1 ps-4">
              {general.map((text) => (
                <li key={text}>
                  <Text type="body" size="sm">
                    {text}
                  </Text>
                </li>
              ))}
            </ul>
          </Card>
        )}
        <div className={cn("flex gap-8", wide ? "flex-col @min-[1100px]:flex-row" : "flex-col")}>
          <div className="flex min-w-0 flex-1 flex-col gap-5">
            <StepForm
              draft={draft}
              definition={definition}
              index={index}
              names={names}
              functions={functions}
              problems={problems}
            />
            <TextInput
              label={t("flow_editor_note")}
              description={t("flow_editor_note_hint")}
              value={note}
              onChange={setNote}
              placeholder={t("flow_editor_note_placeholder")}
            />
            {!isNew && (
              <div className="border-ax-border flex flex-col gap-2 border-t pt-4">
                <Button
                  label={t("flow_editor_delete_step")}
                  variant="destructive"
                  size="sm"
                  icon={<Trash2 className="size-4" />}
                  onClick={() => setConfirmDelete(true)}
                  className="self-start"
                />
              </div>
            )}
          </div>
          {reference}
        </div>
      </div>
      {saveBar}
    </form>
  );

  const body = wide ? (
    <div className="@container flex min-h-0 flex-1">
      <FlowStepNav
        definition={definition}
        currentKey={isNew ? null : step.key}
        onSelect={() => {}}
        onOverview={onCancel}
        locked
        lockedNote={t("flow_editor_nav_locked")}
      />
      <div className="min-h-0 min-w-0 flex-1 overflow-y-auto">{main}</div>
    </div>
  ) : (
    <div className="min-h-0 flex-1 overflow-y-auto">{main}</div>
  );

  return (
    <>
      {body}
      <ConfirmDialogControlled
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title={t("flow_editor_delete_title", { name: step.name })}
        description={
          readers.length > 0
            ? t("flow_editor_delete_description_readers", {
                names: readers.map((use) => use.step.name).join(", ")
              })
            : t("flow_editor_delete_description")
        }
        confirmLabel={t("flow_editor_delete_step")}
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </>
  );
}
