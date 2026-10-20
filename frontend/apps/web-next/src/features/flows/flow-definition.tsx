"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { ClickableCard } from "@astryxdesign/core/ClickableCard";
import { DropdownMenu } from "@astryxdesign/core/DropdownMenu";
import { List, ListItem } from "@astryxdesign/core/List";
import { Heading, Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";
import {
  ArrowDown,
  ArrowUp,
  ChevronRight,
  Clock,
  Info,
  MoreHorizontal,
  Pencil,
  User
} from "lucide-react";
import { useTranslations } from "next-intl";
import { Fragment, useState, type ReactNode } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { FlowInputsEditor } from "./flow-inputs-editor";
import { StepKindPicker } from "./step-kind-picker";
import { functionAvailability } from "./flow-functions";
import { formatDuration, stepKindLabel } from "./flow-labels";
import {
  flowOversight,
  stepProduces,
  stepReads,
  type FlowOversight,
  type StepProduces,
  type StepRead
} from "./flow-reads";
import { NO_NAMES, shortId, type FlowNames } from "./flow-step-summary";
import { TemplateText } from "./flow-template";
import {
  formFieldsOf,
  stepsOf,
  type FlowDefinition as Definition,
  type FlowFunctionPublic,
  type FlowPublic,
  type FlowStep,
  type FormField,
  type FormFieldType,
  type StepKind
} from "./types";

/** Whether the overview reads the flow, or changes it (after "Redigera"). */
export type FlowOverviewMode = "view" | "edit";

type Translate = ReturnType<typeof useTranslations>;

const FIELD_TYPE_KEYS: Record<FormFieldType, string> = {
  text: "flow_field_type_text",
  number: "flow_field_type_number",
  select: "flow_field_type_select",
  file: "flow_field_type_file",
  audio: "flow_field_type_audio"
};

const OVERSIGHT_COUNT_KEYS: Record<StepKind, string> = {
  llm: "flow_oversight_count_llm",
  compose: "flow_oversight_count_compose",
  document: "flow_oversight_count_document",
  function: "flow_oversight_count_function",
  review: "flow_oversight_count_review",
  transcribe: "flow_oversight_count_transcribe"
};

/** A section heading of the panel: small, secondary, upper case. */
export function SectionHeading({ id, children }: { id?: string; children: ReactNode }) {
  return (
    <Heading
      level={3}
      id={id}
      color="secondary"
      className="m-0 text-[11px] font-semibold tracking-wide uppercase"
    >
      {children}
    </Heading>
  );
}

/** "text · obligatorisk · Nämnd, AU": the type line of a run input. */
export function fieldTypeLine(field: FormField, t: Translate): string {
  const parts = [
    t(FIELD_TYPE_KEYS[field.type] ?? "flow_field_type_text"),
    field.required === false ? t("optional") : t("required")
  ];
  if (field.type === "select" && field.options?.length) parts.push(field.options.join(", "));
  return parts.join(" · ");
}

/** The text of a source a step reads: the input's label, "Steg 2 · Granska", a knowledge name. */
export function readLabel(read: StepRead, names: FlowNames, t: Translate): string {
  switch (read.kind) {
    case "form":
      return read.field?.label ?? read.key;
    case "step":
      return read.index !== null
        ? `${t("flow_ref_step", { index: read.index + 1 })} · ${read.step?.name ?? read.key}`
        : `${t("flow_ref_step_unknown")} · ${read.key}`;
    case "knowledge": {
      const resolve = read.source === "collection" ? names.collectionName : names.websiteName;
      return resolve?.(read.id) ?? shortId(read.id);
    }
  }
}

/** A run input is blue, an earlier step purple, a person's checkpoint orange. */
export function readColor(read: StepRead): "blue" | "purple" | "orange" | "default" {
  if (read.kind === "form") return "blue";
  if (read.kind === "step") return read.step?.kind === "review" ? "orange" : "purple";
  return "default";
}

/** A source a step reads, as a token coloured by where it comes from. */
export function ReadToken({ read, names }: { read: StepRead; names: FlowNames }) {
  const t = useTranslations();
  return <Token size="sm" color={readColor(read)} label={readLabel(read, names, t)} />;
}

/** "Text", "Strukturerad data: a, b", "Word-fil · <filename>": what a step gives. */
function ProducesLine({
  produces,
  definition
}: {
  produces: StepProduces;
  definition: Definition;
}) {
  const t = useTranslations();
  switch (produces.kind) {
    case "text":
      return t("flow_produces_text");
    case "json":
      return produces.fields.length > 0 ? (
        <>
          {t("flow_produces_json")}
          {": "}
          <Text type="code" size="xsm">
            {produces.fields.join(", ")}
          </Text>
        </>
      ) : (
        t("flow_produces_json")
      );
    case "file": {
      const format =
        produces.format === "pdf"
          ? t("flow_produces_pdf")
          : produces.format === "template"
            ? t("flow_produces_template")
            : t("flow_produces_docx");
      return produces.filename ? (
        <>
          {format}
          {" · "}
          <TemplateText template={produces.filename} definition={definition} />
        </>
      ) : (
        format
      );
    }
    case "function":
      return t("flow_produces_function", { tool: produces.tool });
    case "transcript":
      return t("flow_produces_transcript");
    case "review":
      return null;
  }
}

/** The number bubble on the rail, or the person glyph for a review step. */
export function StepGlyph({ step, index }: { step: FlowStep; index: number }) {
  return step.kind === "review" ? (
    <span
      aria-hidden="true"
      className="bg-ax-orange-muted text-ax-orange flex size-7 shrink-0 items-center justify-center rounded-full"
    >
      <User className="size-3.5" />
    </span>
  ) : (
    <span
      aria-hidden="true"
      className="border-ax-border-strong bg-ax-surface text-ax-text-secondary flex size-7 shrink-0 items-center justify-center rounded-full border-2 text-xs font-semibold tabular-nums"
    >
      {index + 1}
    </span>
  );
}

/** The body of a review card: what the pause means, its time limit, what a rejection does. */
function ReviewCardBody({ step, definition }: { step: FlowStep; definition: Definition }) {
  const t = useTranslations();
  if (step.kind !== "review") return null;
  const target = stepReads(step, definition).find((read) => read.kind === "step");
  const index = target?.kind === "step" && target.index !== null ? target.index + 1 : null;
  const sentence =
    index === null
      ? t("flow_review_card_unknown")
      : (step.mode ?? "edit") === "edit"
        ? t("flow_review_card_edit", { index })
        : t("flow_review_card_view", { index });
  return (
    <>
      <Text type="body" size="sm" as="p" display="block" className="m-0 leading-snug">
        {sentence}
      </Text>
      <span className="flex flex-wrap gap-1">
        <Token
          size="sm"
          color="orange"
          icon={<Clock aria-hidden="true" className="size-3" />}
          label={
            step.expires_after_seconds
              ? t("flow_review_time_limit", {
                  duration: formatDuration(step.expires_after_seconds, t)
                })
              : t("flow_review_no_time_limit")
          }
        />
        <Token size="sm" label={t("flow_review_rejected")} />
      </span>
    </>
  );
}

/** "Läser: tokens · Ger: line" for every step but a review. */
function StepCardBody({
  step,
  definition,
  names,
  functions
}: {
  step: FlowStep;
  definition: Definition;
  names: FlowNames;
  functions?: FlowFunctionPublic[];
}) {
  const t = useTranslations();
  const reads = stepReads(step, definition);
  const cannotRun =
    step.kind === "function" && !["ok", "unknown"].includes(functionAvailability(functions, step));
  return (
    <span className="grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-2.5 gap-y-1 text-[12.5px]">
      <Text type="supporting" size="2xs" weight="semibold" className="tracking-wide uppercase">
        {t("flow_reads")}
      </Text>
      <span className="flex flex-wrap gap-1">
        {reads.length === 0 ? (
          <Text type="supporting" size="sm">
            {t("flow_reads_nothing")}
          </Text>
        ) : (
          reads.map((read) => (
            <ReadToken
              key={`${read.kind}:${read.kind === "knowledge" ? read.id : read.key}`}
              read={read}
              names={names}
            />
          ))
        )}
      </span>
      <Text type="supporting" size="2xs" weight="semibold" className="tracking-wide uppercase">
        {t("flow_gives")}
      </Text>
      <span className="flex min-w-0 flex-wrap items-center gap-1.5">
        <Text type="body" size="sm" className="min-w-0 leading-snug break-words">
          <ProducesLine produces={stepProduces(step)} definition={definition} />
        </Text>
        {cannotRun && <Token size="sm" color="orange" label={t("flow_function_cannot_run")} />}
      </span>
    </span>
  );
}

/**
 * One step of the overview: its number (or the person glyph), name and
 * kind, then what it reads and gives. A clickable card when a step can be
 * opened; a plain one otherwise (a revision in the history).
 */
export function FlowStepCard({
  step,
  index,
  count,
  definition,
  names = NO_NAMES,
  functions,
  onOpen,
  onMove
}: {
  step: FlowStep;
  index: number;
  /** How many steps the flow has (the last cannot move down). */
  count?: number;
  definition: Definition;
  names?: FlowNames;
  functions?: FlowFunctionPublic[];
  onOpen?: (key: string) => void;
  /** Edit mode: the card's menu moves the step up or down. */
  onMove?: (key: string, direction: -1 | 1) => void;
}) {
  const t = useTranslations();
  const review = step.kind === "review";
  const last = count !== undefined && index === count - 1;
  const content = (
    <div className="flex min-w-0 flex-col gap-2">
      <div className="flex items-center gap-2">
        <Text type="body" weight="semibold" maxLines={1} className="min-w-0 flex-1">
          {step.name}
        </Text>
        <Badge variant={review ? "orange" : "neutral"} label={stepKindLabel(step.kind, t)} />
        {onMove ? (
          <DropdownMenu
            button={{
              label: t("flow_step_menu", { name: step.name }),
              icon: <MoreHorizontal className="size-4" />,
              isIconOnly: true,
              variant: "ghost",
              size: "sm"
            }}
            hasChevron={false}
            placement="below"
            alignment="end"
            items={[
              {
                id: "up",
                label: t("flow_editor_move_up"),
                icon: <ArrowUp className="size-4" />,
                isDisabled: index === 0,
                onClick: () => onMove(step.key, -1)
              },
              {
                id: "down",
                label: t("flow_editor_move_down"),
                icon: <ArrowDown className="size-4" />,
                isDisabled: last,
                onClick: () => onMove(step.key, 1)
              }
            ]}
          />
        ) : (
          onOpen && (
            <ChevronRight aria-hidden="true" className="text-ax-text-tertiary size-4 shrink-0" />
          )
        )}
      </div>
      {review ? (
        <ReviewCardBody step={step} definition={definition} />
      ) : (
        <StepCardBody step={step} definition={definition} names={names} functions={functions} />
      )}
    </div>
  );
  return (
    <li className="flex items-start gap-2.5">
      <StepGlyph step={step} index={index} />
      {onOpen ? (
        <ClickableCard
          label={t("flow_step_open", { index: index + 1, name: step.name })}
          onClick={() => onOpen(step.key)}
          padding={3}
          variant={review ? "orange" : "default"}
          className="min-w-0 flex-1"
        >
          {content}
        </ClickableCard>
      ) : (
        <Card padding={3} variant={review ? "orange" : "default"} className="min-w-0 flex-1">
          <div
            role="group"
            aria-label={t("flow_step_label", { index: index + 1, name: step.name })}
          >
            {content}
          </div>
        </Card>
      )}
    </li>
  );
}

/** Counts by kind and the sentence that says where a person decides. */
function OversightStrip({ oversight }: { oversight: FlowOversight }) {
  const t = useTranslations();
  const counts = (Object.entries(oversight.counts) as [StepKind, number][]).filter(
    ([, count]) => count > 0
  );
  const gate = oversight.gate;
  const sentence =
    gate === null
      ? t("flow_oversight_none")
      : [
          gate.targetIndex !== null
            ? t("flow_oversight_gate", { target: gate.targetIndex + 1 })
            : t("flow_oversight_gate_unknown"),
          gate.afterFrom > gate.afterTo
            ? null
            : gate.afterFrom === gate.afterTo
              ? t("flow_oversight_after_one", { from: gate.afterFrom })
              : t("flow_oversight_after_many", { from: gate.afterFrom, to: gate.afterTo })
        ]
          .filter(Boolean)
          .join(" ");
  return (
    <Card variant="muted" padding={3} className="flex flex-col gap-1.5">
      <div
        role="group"
        aria-label={t("flow_oversight_label")}
        className="flex flex-wrap gap-x-3 gap-y-1"
      >
        {counts.map(([kind, count]) => (
          <Text
            key={kind}
            type="body"
            size="sm"
            weight="medium"
            className={kind === "review" ? "text-ax-orange" : undefined}
          >
            {t(OVERSIGHT_COUNT_KEYS[kind], { count })}
          </Text>
        ))}
      </div>
      <Text type="supporting" size="sm" as="p" display="block" className="m-0 leading-snug">
        {sentence}
      </Text>
    </Card>
  );
}

/**
 * A flow as it is defined: description, status and how it is overseen, the
 * inputs a run asks for, then the steps as cards that say what each reads
 * and gives. A card opens the step in the step view when `onOpenStep` is
 * given; nothing here changes the flow.
 */
export function FlowDefinition({
  flow,
  names = NO_NAMES,
  onOpenStep,
  canEdit = false,
  functions,
  mode = "view",
  onInsertStep,
  onMoveStep,
  onSaveInputs,
  onEdit,
  saving = false,
  problems = []
}: {
  flow: FlowPublic;
  names?: FlowNames;
  /** Opens a step (its key) in the step view; without it the cards are plain. */
  onOpenStep?: (key: string) => void;
  /** Whether the reader may press "Redigera" (the note at the end says so). */
  canEdit?: boolean;
  /** What the space can call; a function step that cannot run is marked. */
  functions?: FlowFunctionPublic[];
  mode?: FlowOverviewMode;
  /** Edit mode: a kind picked on the rail opens the editor for a new step at the index. */
  onInsertStep?: (kind: StepKind, index: number) => void;
  /** Edit mode: moves a step one place up or down (saved at once). */
  onMoveStep?: (key: string, direction: -1 | 1) => void;
  /** Edit mode: saves the run inputs as the dialog hands them back; the dialog closes when it resolves. */
  onSaveInputs?: (fields: FormField[]) => Promise<unknown>;
  /** View mode: enters edit mode (offered where there are no steps yet). */
  onEdit?: () => void;
  /** An overview save (a move, the inputs) is on its way. */
  saving?: boolean;
  /** Problems the last overview save was refused for. */
  problems?: string[];
}) {
  const t = useTranslations();
  const { definition } = flow;
  const fields = formFieldsOf(definition);
  const steps = stepsOf(definition);
  const editing = mode === "edit";
  const [inputsOpen, setInputsOpen] = useState(false);

  return (
    <div className="flex flex-col gap-5 p-4">
      <section aria-label={t("flow_section_about")} className="flex flex-col gap-2.5">
        {flow.description ? (
          <Text type="supporting" size="sm" as="p" display="block" className="m-0 leading-snug">
            {flow.description}
          </Text>
        ) : null}
        {steps.length > 0 && <OversightStrip oversight={flowOversight(definition)} />}
      </section>

      {problems.length > 0 && (
        <Banner
          status="error"
          title={t("flow_overview_problems_title")}
          description={
            <ul className="m-0 flex list-disc flex-col gap-0.5 ps-4">
              {problems.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
          }
          collapsible={false}
        />
      )}

      <section aria-labelledby="flow-inputs-heading" className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <SectionHeading id="flow-inputs-heading">{t("flow_section_inputs")}</SectionHeading>
          {editing && onSaveInputs && (
            <Button
              label={fields.length === 0 ? t("flow_input_add") : t("flow_edit")}
              variant="ghost"
              size="sm"
              icon={<Pencil className="size-4" />}
              onClick={() => setInputsOpen(true)}
            />
          )}
        </div>
        {fields.length === 0 ? (
          <Text type="supporting" size="sm" as="p" display="block" className="m-0">
            {t("flow_inputs_none")}
          </Text>
        ) : (
          <List density="compact" hasDividers edgeCompensation="inline">
            {fields.map((field) => (
              <ListItem
                key={field.key}
                label={field.label}
                description={
                  <>
                    {field.description && (
                      <Text type="supporting" size="xsm" display="block">
                        {field.description}
                      </Text>
                    )}
                    <Text type="supporting" size="xsm" display="block">
                      {fieldTypeLine(field, t)}
                    </Text>
                  </>
                }
              />
            ))}
          </List>
        )}
      </section>

      <section aria-labelledby="flow-steps-heading" className="flex flex-col gap-2">
        <SectionHeading id="flow-steps-heading">{t("flow_section_steps")}</SectionHeading>
        {steps.length === 0 ? (
          editing && onInsertStep ? (
            <EmptyState
              isCompact
              headingLevel={4}
              title={t("flow_steps_none")}
              description={t("flow_steps_empty_edit_description")}
              actions={
                <StepKindPicker
                  label={t("flow_add_step_yourself")}
                  onPick={(kind) => onInsertStep(kind, 0)}
                />
              }
            />
          ) : canEdit && onEdit ? (
            <EmptyState
              isCompact
              headingLevel={4}
              title={t("flow_steps_none")}
              description={t("flow_steps_empty_view_description")}
              actions={
                <Button
                  label={t("flow_edit")}
                  size="sm"
                  icon={<Pencil className="size-4" />}
                  onClick={onEdit}
                />
              }
            />
          ) : (
            <Text type="supporting" size="sm" as="p" display="block" className="m-0">
              {t("flow_steps_none")}
            </Text>
          )
        ) : (
          <ol className="before:bg-ax-border relative m-0 flex list-none flex-col gap-2 p-0 before:absolute before:start-[13px] before:top-3 before:bottom-3 before:w-px">
            {steps.map((step, index) => (
              <Fragment key={step.id ?? step.key}>
                <FlowStepCard
                  step={step}
                  index={index}
                  count={steps.length}
                  definition={definition}
                  names={names}
                  functions={functions}
                  onOpen={onOpenStep}
                  onMove={editing && onMoveStep ? onMoveStep : undefined}
                />
                {editing && onInsertStep && index < steps.length - 1 && (
                  <li className="flex h-6 items-center">
                    <span className="bg-ax-surface relative z-[1] flex size-7 shrink-0 items-center justify-center">
                      <StepKindPicker
                        label={t("flow_insert_step_after", { index: index + 1 })}
                        onPick={(kind) => onInsertStep(kind, index + 1)}
                        iconOnly
                      />
                    </span>
                  </li>
                )}
              </Fragment>
            ))}
            {editing && onInsertStep && (
              <li className="flex items-center gap-2.5">
                <span aria-hidden="true" className="bg-ax-surface relative z-[1] size-7 shrink-0" />
                <StepKindPicker
                  label={t("flow_add_step_last")}
                  onPick={(kind) => onInsertStep(kind, steps.length)}
                />
              </li>
            )}
          </ol>
        )}
      </section>
      {editing && onSaveInputs && inputsOpen && (
        <FlowInputsEditor
          definition={definition}
          open={inputsOpen}
          onOpenChange={setInputsOpen}
          onSave={onSaveInputs}
          saving={saving}
        />
      )}

      {onOpenStep && (
        <Card variant="muted" padding={3}>
          <section aria-label={t("flow_section_changes")} className="flex gap-2.5">
            <Info aria-hidden="true" className="text-ax-text-secondary mt-0.5 size-4 shrink-0" />
            <Text type="body" size="sm" as="p" display="block" className="m-0 leading-snug">
              {editing
                ? t("flow_edit_mode_note")
                : canEdit
                  ? t("flow_view_mode_note")
                  : t("flow_view_mode_note_readonly")}
            </Text>
          </section>
        </Card>
      )}
    </div>
  );
}
