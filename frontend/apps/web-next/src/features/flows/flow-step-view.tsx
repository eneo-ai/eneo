"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { IconButton } from "@astryxdesign/core/IconButton";
import { List, ListItem } from "@astryxdesign/core/List";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { Heading, Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";
import {
  ArrowLeft,
  BookOpen,
  Braces,
  ChevronLeft,
  ChevronRight,
  FileText,
  Paperclip,
  Pencil,
  TextCursorInput,
  User
} from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { ClientTime } from "@/components/composites/client-time";
import { cn } from "@/lib/utils";
import { readColor, readLabel, SectionHeading, StepGlyph } from "./flow-definition";
import { MonoBlock } from "./flow-fields";
import { functionAvailability, functionOf } from "./flow-functions";
import { formatDuration, functionPurposeLabel, stepKindLabel } from "./flow-labels";
import {
  schemaFieldRows,
  stepProduces,
  stepReads,
  stepUsedBy,
  type SchemaFieldRow,
  type StepRead
} from "./flow-reads";
import { FlowStepNav } from "./flow-step-nav";
import { Named, NO_NAMES, type FlowNames } from "./flow-step-summary";
import { TemplateText } from "./flow-template";
import {
  formFieldsOf,
  stepsOf,
  type DocumentStep,
  type FlowDefinition,
  type FlowFunctionPublic,
  type FlowStep,
  type FunctionStep,
  type LlmStep,
  type ReviewStep,
  type StepOriginPublic,
  type TranscribeStep
} from "./types";

type Translate = ReturnType<typeof useTranslations>;

const SHAPE_KEYS: Record<SchemaFieldRow["shape"], string> = {
  text: "flow_schema_shape_text",
  number: "flow_schema_shape_number",
  boolean: "flow_schema_shape_boolean",
  list: "flow_schema_shape_list",
  object: "flow_schema_shape_object",
  one_of: "flow_schema_shape_one_of",
  any: "flow_schema_shape_any"
};

/** "Text", "Lista med text", "Ett av a, b": a schema field's shape in words. */
export function schemaShapeLabel(row: SchemaFieldRow, t: Translate): string {
  switch (row.shape) {
    case "list": {
      const [items, ...rest] = row.detail;
      const inner = items
        ? schemaShapeLabel({ ...row, shape: items as SchemaFieldRow["shape"], detail: rest }, t)
        : t("flow_schema_shape_any");
      return t("flow_schema_shape_list", { items: inner.toLocaleLowerCase() });
    }
    case "object":
      return row.detail.length > 0
        ? t("flow_schema_shape_object", { fields: row.detail.join(", ") })
        : t("flow_schema_shape_object_plain");
    case "one_of":
      return t("flow_schema_shape_one_of", { values: row.detail.join(", ") });
    default:
      return t(SHAPE_KEYS[row.shape]);
  }
}

function Section({
  id,
  title,
  children,
  className
}: {
  id: string;
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section aria-labelledby={id} className={cn("flex min-w-0 flex-col gap-2", className)}>
      <SectionHeading id={id}>{title}</SectionHeading>
      {children}
    </section>
  );
}

/** A paragraph of a template as prose, its references shown as badges. */
function Prose({ template, definition }: { template: string; definition: FlowDefinition }) {
  return (
    <Text
      type="body"
      as="p"
      display="block"
      className="m-0 max-w-prose leading-relaxed whitespace-pre-wrap"
    >
      <TemplateText template={template} definition={definition} />
    </Text>
  );
}

function readIcon(read: StepRead) {
  if (read.kind === "knowledge") return <BookOpen aria-hidden="true" className="size-4" />;
  if (read.kind === "form") {
    return read.file || read.field?.type === "file" || read.field?.type === "audio" ? (
      <Paperclip aria-hidden="true" className="size-4" />
    ) : (
      <TextCursorInput aria-hidden="true" className="size-4" />
    );
  }
  return read.step?.kind === "review" ? (
    <User aria-hidden="true" className="size-4" />
  ) : (
    <FileText aria-hidden="true" className="size-4" />
  );
}

/** "Fil · bifogas", "Indata · valfri", "Steg 2 · granskat resultat": what a read source is. */
function readDetail(read: StepRead, t: Translate): string {
  switch (read.kind) {
    case "form": {
      const field = read.field;
      const file = read.file || field?.type === "file" || field?.type === "audio";
      if (file) return t("flow_reads_file_detail");
      return field?.required === false
        ? t("flow_reads_input_optional_detail")
        : t("flow_reads_input_detail");
    }
    case "step":
      if (read.step?.kind === "review") return t("flow_reads_review_detail");
      return read.previous ? t("flow_reads_previous_detail") : t("flow_reads_step_detail");
    case "knowledge":
      return t("flow_reads_knowledge");
  }
}

/** What the step reads, one row per source, and (for a model step) how the input is assembled. */
function ReadsSection({
  step,
  definition,
  names,
  onSelectStep
}: {
  step: FlowStep;
  definition: FlowDefinition;
  names: FlowNames;
  onSelectStep: (key: string) => void;
}) {
  const t = useTranslations();
  const reads = stepReads(step, definition);
  const hasKnowledge = reads.some((read) => read.kind === "knowledge");
  return (
    <Section id="flow-step-reads" title={t("flow_section_reads")}>
      {reads.length === 0 ? (
        <Text type="supporting" size="sm">
          {t("flow_reads_none")}
        </Text>
      ) : (
        <List density="compact">
          {reads.map((read) => (
            <ListItem
              key={`${read.kind}:${read.kind === "knowledge" ? read.id : read.key}`}
              label={readLabel(read, names, t)}
              description={readDetail(read, t)}
              startContent={<span className="text-ax-text-secondary">{readIcon(read)}</span>}
              onClick={read.kind === "step" && read.step ? () => onSelectStep(read.key) : undefined}
            />
          ))}
        </List>
      )}
      {step.kind === "llm" && !hasKnowledge && (
        <Text type="supporting" size="sm">
          {t("flow_reads_knowledge_none")}
        </Text>
      )}
      {step.kind === "llm" && (
        <Collapsible trigger={t("flow_show_input_template")} defaultIsOpen={false}>
          <MonoBlock>
            <TemplateText template={step.input ?? "{{previous}}"} definition={definition} />
          </MonoBlock>
        </Collapsible>
      )}
    </Section>
  );
}

function ModelSection({ step, names }: { step: LlmStep; names: FlowNames }) {
  const t = useTranslations();
  const kwargs = Object.entries(step.model_kwargs ?? {}).filter(([, value]) => value != null);
  return (
    <Section id="flow-step-model" title={t("flow_section_model")}>
      <MetadataList>
        <MetadataListItem label={t("model")}>
          {step.model_id ? (
            <Named id={step.model_id} resolve={names.modelName} />
          ) : (
            <>
              {t("flow_param_model_default")}
              <Text type="supporting" size="xsm" display="block">
                {t("flow_model_default_detail")}
              </Text>
            </>
          )}
        </MetadataListItem>
        {kwargs.length === 0 ? (
          <MetadataListItem label={t("flow_model_settings")}>
            {t("flow_model_settings_default")}
          </MetadataListItem>
        ) : (
          kwargs.map(([key, value]) => (
            <MetadataListItem key={key} label={key}>
              {String(value)}
            </MetadataListItem>
          ))
        )}
      </MetadataList>
    </Section>
  );
}

/** The fields of a JSON output as a table, the raw schema behind a disclosure. */
function JsonOutput({ schema }: { schema: Record<string, unknown> }) {
  const t = useTranslations();
  const rows = schemaFieldRows(schema);
  const required = rows.filter((row) => row.required).length;
  return (
    <>
      <div className="flex items-center gap-2">
        <Braces aria-hidden="true" className="text-ax-text-secondary size-4 shrink-0" />
        <Text type="body" weight="medium">
          {t("flow_produces_json_fields", { count: rows.length })}
        </Text>
        {rows.length > 0 && (
          <Text type="supporting" size="sm">
            {required === rows.length
              ? t("flow_schema_required_all")
              : t("flow_schema_required_some", { count: required, total: rows.length })}
          </Text>
        )}
      </div>
      {rows.length > 0 && (
        <MetadataList>
          {rows.map((row) => (
            <MetadataListItem key={row.name} label={row.name}>
              {schemaShapeLabel(row, t)}
              {!row.required && (
                <Text type="supporting" size="xsm">
                  {" · "}
                  {t("flow_schema_optional")}
                </Text>
              )}
            </MetadataListItem>
          ))}
        </MetadataList>
      )}
      <Collapsible trigger={t("flow_show_schema")} defaultIsOpen={false}>
        <MonoBlock>{JSON.stringify(schema, null, 2)}</MonoBlock>
      </Collapsible>
    </>
  );
}

function ProducesSection({
  step,
  definition,
  names
}: {
  step: FlowStep;
  definition: FlowDefinition;
  names: FlowNames;
}) {
  const t = useTranslations();
  const produces = stepProduces(step);
  let body: ReactNode;
  switch (produces.kind) {
    case "json":
      body = step.kind === "llm" && step.output?.type === "json" && (
        <JsonOutput schema={step.output.schema} />
      );
      break;
    case "text":
      body = (
        <Text type="body">
          {t("flow_produces_text")}
          <Text type="supporting" size="sm" display="block">
            {t("flow_produces_text_detail")}
          </Text>
        </Text>
      );
      break;
    case "file":
      body = step.kind === "document" && (
        <MetadataList>
          <MetadataListItem label={t("flow_param_format")}>
            {produces.format === "pdf"
              ? t("flow_produces_pdf")
              : produces.format === "template"
                ? t("flow_produces_template")
                : t("flow_produces_docx")}
          </MetadataListItem>
          <MetadataListItem label={t("title")}>
            {step.title ? (
              <TemplateText template={step.title} definition={definition} />
            ) : (
              t("flow_param_title_default")
            )}
          </MetadataListItem>
          <MetadataListItem label={t("flow_param_filename")}>
            {step.filename ? (
              <TemplateText template={step.filename} definition={definition} />
            ) : (
              t("flow_param_filename_default")
            )}
          </MetadataListItem>
        </MetadataList>
      );
      break;
    case "function":
      body = (
        <Text type="body">
          {t("flow_produces_function", { tool: produces.tool })}
          <Text type="supporting" size="sm" display="block">
            {t("flow_produces_function_detail")}
          </Text>
        </Text>
      );
      break;
    case "transcript":
      body = (
        <Text type="body">
          {t("flow_produces_transcript")}
          <Text type="supporting" size="sm" display="block">
            {t("flow_produces_transcript_detail")}
          </Text>
        </Text>
      );
      break;
    case "review":
      body = null;
  }
  void names;
  return (
    <Section id="flow-step-produces" title={t("flow_section_produces")}>
      {body}
    </Section>
  );
}

/** The later steps that read this step's output. */
function UsedBySection({
  step,
  definition,
  onSelectStep
}: {
  step: FlowStep;
  definition: FlowDefinition;
  onSelectStep: (key: string) => void;
}) {
  const t = useTranslations();
  const uses = stepUsedBy(step.key, definition);
  return (
    <Section id="flow-step-used-by" title={t("flow_section_used_by")}>
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
                use.via === "review"
                  ? t("flow_used_by_review")
                  : use.via === "previous"
                    ? t("flow_used_by_previous")
                    : t("flow_used_by_key")
              }
              startContent={<StepGlyph step={use.step} index={use.index} />}
              onClick={() => onSelectStep(use.step.key)}
            />
          ))}
        </List>
      )}
    </Section>
  );
}

function DocumentSection({
  step,
  definition,
  names
}: {
  step: DocumentStep;
  definition: FlowDefinition;
  names: FlowNames;
}) {
  const t = useTranslations();
  const values = Object.entries(step.values ?? {});
  return (
    <Section id="flow-step-document" title={t("flow_section_document")}>
      {step.template_file_id ? (
        <MetadataList>
          <MetadataListItem label={t("flow_param_template_file")}>
            <Named id={step.template_file_id} resolve={names.fileName} />
          </MetadataListItem>
          {values.map(([name, template]) => (
            <MetadataListItem key={name} label={name}>
              <TemplateText template={template} definition={definition} />
            </MetadataListItem>
          ))}
        </MetadataList>
      ) : (
        <MonoBlock>
          <TemplateText template={step.content ?? ""} definition={definition} />
        </MonoBlock>
      )}
    </Section>
  );
}

/** Why a function step cannot run as it is, for the warning above its settings. */
export function functionWarning(
  availability: ReturnType<typeof functionAvailability>,
  step: FunctionStep,
  provider: string | null,
  t: Translate
): string | null {
  switch (availability) {
    case "disabled":
      return t("flow_function_warning_disabled");
    case "unavailable":
      return t("flow_function_warning_unavailable");
    case "unknown_tool":
      return t("flow_function_warning_unknown_tool", {
        tool: step.tool,
        provider: provider ?? t("flow_function_provider_unknown")
      });
    default:
      return null;
  }
}

function FunctionSection({
  step,
  definition,
  functions
}: {
  step: FunctionStep;
  definition: FlowDefinition;
  functions?: FlowFunctionPublic[];
}) {
  const t = useTranslations();
  const entries = Object.entries(step.arguments ?? {});
  const entry = functionOf(functions, step.purpose);
  const warning = functionWarning(
    functionAvailability(functions, step),
    step,
    entry?.provider ?? null,
    t
  );
  return (
    <Section id="flow-step-function" title={t("flow_section_function")}>
      {warning && (
        <Banner
          status="warning"
          title={t("flow_function_warning_title")}
          description={warning}
          collapsible={false}
        />
      )}
      <MetadataList>
        <MetadataListItem label={t("flow_param_function")}>
          {functionPurposeLabel(step.purpose, t)}
          {" · "}
          <Text type="code" size="xsm">
            {step.tool}
          </Text>
        </MetadataListItem>
        {entry?.provider && (
          <MetadataListItem label={t("flow_function_provider")}>{entry.provider}</MetadataListItem>
        )}
        {entries.length === 0 ? (
          <MetadataListItem label={t("flow_param_arguments")}>
            {t("flow_param_none")}
          </MetadataListItem>
        ) : (
          entries.map(([name, value]) => (
            <MetadataListItem key={name} label={name}>
              {typeof value === "string" ? (
                <TemplateText template={value} definition={definition} />
              ) : (
                <Text type="code" size="xsm">
                  {JSON.stringify(value)}
                </Text>
              )}
            </MetadataListItem>
          ))
        )}
      </MetadataList>
    </Section>
  );
}

function TranscribeSection({
  step,
  definition,
  names
}: {
  step: TranscribeStep;
  definition: FlowDefinition;
  names: FlowNames;
}) {
  const t = useTranslations();
  const mapping = step.speaker_mapping;
  const field = stepReads(step, definition).find((read) => read.kind === "form");
  const participants = mapping?.participants_field ?? null;
  const speakers = step.speaker_labels
    ? [
        step.max_speakers
          ? t("flow_param_speakers_max", { count: step.max_speakers })
          : t("flow_param_speakers_on"),
        participants
          ? t("flow_param_speakers_from", {
              field:
                formFieldsOf(definition).find((candidate) => candidate.key === participants)
                  ?.label ?? participants
            })
          : mapping?.infer_names
            ? t("flow_param_speakers_infer")
            : null
      ]
        .filter(Boolean)
        .join(" · ")
    : t("flow_param_speakers_off");
  return (
    <Section id="flow-step-transcribe" title={t("flow_section_transcribe")}>
      <MetadataList>
        <MetadataListItem label={t("flow_param_source")}>
          {field && <Token size="sm" color={readColor(field)} label={readLabel(field, names, t)} />}
        </MetadataListItem>
        <MetadataListItem label={t("model")}>
          {step.transcription_model_id ? (
            <Named id={step.transcription_model_id} resolve={names.transcriptionModelName} />
          ) : (
            t("flow_param_model_default")
          )}
        </MetadataListItem>
        <MetadataListItem label={t("language")}>
          {step.language ?? t("flow_param_language_auto")}
        </MetadataListItem>
        <MetadataListItem label={t("flow_param_speakers")}>{speakers}</MetadataListItem>
      </MetadataList>
    </Section>
  );
}

/** A review step: what the pause does, in three sentences, then its settings. */
function ReviewSections({
  step,
  definition,
  onSelectStep
}: {
  step: ReviewStep;
  definition: FlowDefinition;
  onSelectStep: (key: string) => void;
}) {
  const t = useTranslations();
  const steps = stepsOf(definition);
  const index = steps.findIndex((candidate) => candidate.key === step.key);
  const target = stepReads(step, definition).find((read) => read.kind === "step");
  const targetIndex = target?.kind === "step" ? target.index : null;
  const edit = (step.mode ?? "edit") === "edit";
  const next = index >= 0 && index + 1 < steps.length ? index + 2 : null;
  return (
    <>
      <Card variant="orange" padding={3}>
        <Section id="flow-step-review-how" title={t("flow_section_review")}>
          <List listStyle="decimal" density="compact">
            <ListItem
              label={
                targetIndex !== null
                  ? t("flow_review_how_1", { index: targetIndex + 1 })
                  : t("flow_review_how_1_unknown")
              }
            />
            <ListItem label={edit ? t("flow_review_how_2_edit") : t("flow_review_how_2_view")} />
            <ListItem
              label={
                next !== null
                  ? t("flow_review_how_3_next", { index: next })
                  : t("flow_review_how_3_last")
              }
            />
          </List>
        </Section>
      </Card>
      <Section id="flow-step-reviews" title={t("flow_section_reviews")}>
        {target?.kind === "step" && target.step && targetIndex !== null ? (
          <List density="compact">
            <ListItem
              label={`${t("flow_ref_step", { index: targetIndex + 1 })} · ${target.step.name}`}
              description={stepKindLabel(target.step.kind, t)}
              startContent={<StepGlyph step={target.step} index={targetIndex} />}
              onClick={() => onSelectStep(target.key)}
            />
          </List>
        ) : (
          <Text type="supporting" size="sm">
            {t("flow_param_none")}
          </Text>
        )}
      </Section>
      <Section id="flow-step-review-settings" title={t("flow_section_review_mode")}>
        <MetadataList>
          <MetadataListItem label={t("flow_param_review_mode")}>
            {edit ? t("flow_review_mode_edit_title") : t("flow_review_mode_view_title")}
            <Text type="supporting" size="sm" display="block">
              {edit ? t("flow_review_mode_edit_detail") : t("flow_review_mode_view_detail")}
            </Text>
          </MetadataListItem>
          <MetadataListItem label={t("flow_param_time_limit")}>
            {step.expires_after_seconds
              ? t("flow_param_time_limit_value", {
                  duration: formatDuration(step.expires_after_seconds, t)
                })
              : t("flow_param_time_limit_none")}
          </MetadataListItem>
        </MetadataList>
      </Section>
    </>
  );
}

/** Where the step comes from: the chat or the panel, and when. */
export function ProvenanceBadge({ origin }: { origin: StepOriginPublic | null }) {
  const t = useTranslations();
  if (!origin || origin.channel !== "api") return null;
  return (
    <Badge
      variant="orange"
      icon={<User aria-hidden="true" className="size-3" />}
      label={t("flow_changed_manually")}
    />
  );
}

/** Key and kind, for whoever reads the definition as JSON or writes templates; when it last changed. */
function TechFooter({ step, origin }: { step: FlowStep; origin: StepOriginPublic | null }) {
  const t = useTranslations();
  return (
    <div className="border-ax-border flex flex-wrap gap-x-4 gap-y-1 border-t pt-3">
      <Text type="supporting" size="xsm">
        {t("flow_tech_key")}{" "}
        <Text type="code" size="xsm">
          {step.key}
        </Text>
      </Text>
      <Text type="supporting" size="xsm">
        {t("flow_tech_kind")}{" "}
        <Text type="code" size="xsm">
          {step.kind}
        </Text>
      </Text>
      {origin && (
        <Text type="supporting" size="xsm">
          {origin.channel === "api"
            ? t("flow_last_changed_manually")
            : t("flow_last_changed_by_assistant")}{" "}
          <ClientTime value={origin.changed_at} format="date_time" />
          {" · "}
          {t("flow_history_revision", { revision: origin.revision })}
        </Text>
      )}
    </div>
  );
}

/** The sections of a step in execution order: what it reads, what it does, what it gives, who reads it. */
function StepSections({
  step,
  definition,
  names,
  functions,
  onSelectStep,
  wide
}: {
  step: FlowStep;
  definition: FlowDefinition;
  names: FlowNames;
  functions?: FlowFunctionPublic[];
  onSelectStep: (key: string) => void;
  wide: boolean;
}) {
  const t = useTranslations();
  const row = cn("grid gap-6", wide && "@min-[1000px]:grid-cols-2");
  if (step.kind === "review") {
    return (
      <>
        <ReviewSections step={step} definition={definition} onSelectStep={onSelectStep} />
        <UsedBySection step={step} definition={definition} onSelectStep={onSelectStep} />
      </>
    );
  }
  const reads = (
    <ReadsSection step={step} definition={definition} names={names} onSelectStep={onSelectStep} />
  );
  const produces = <ProducesSection step={step} definition={definition} names={names} />;
  const usedBy = <UsedBySection step={step} definition={definition} onSelectStep={onSelectStep} />;
  switch (step.kind) {
    case "llm":
      return (
        <>
          <div className={row}>
            {reads}
            <ModelSection step={step} names={names} />
          </div>
          <Section id="flow-step-prompt" title={t("flow_section_prompt")}>
            <Prose template={step.prompt} definition={definition} />
          </Section>
          <div className={row}>
            {produces}
            {usedBy}
          </div>
        </>
      );
    case "compose":
      return (
        <>
          {reads}
          <Section id="flow-step-template" title={t("flow_param_template")}>
            <MonoBlock>
              <TemplateText template={step.template} definition={definition} />
            </MonoBlock>
          </Section>
          <div className={row}>
            {produces}
            {usedBy}
          </div>
        </>
      );
    case "document":
      return (
        <>
          {reads}
          <DocumentSection step={step} definition={definition} names={names} />
          <div className={row}>
            {produces}
            {usedBy}
          </div>
        </>
      );
    case "function":
      return (
        <>
          {reads}
          <FunctionSection step={step} definition={definition} functions={functions} />
          <div className={row}>
            {produces}
            {usedBy}
          </div>
        </>
      );
    case "transcribe":
      return (
        <>
          <TranscribeSection step={step} definition={definition} names={names} />
          <div className={row}>
            {produces}
            {usedBy}
          </div>
        </>
      );
  }
}

/**
 * One step, read in full: a header with its place in the flow, then its
 * sections in execution order. Maximised (`wide`) it has the navigator at
 * the start and lays related sections side by side; in the narrow panel
 * it is one column under a bar that goes back to the overview and steps
 * to the previous or next step.
 */
export function FlowStepView({
  definition,
  stepKey,
  origins = [],
  names = NO_NAMES,
  functions,
  wide,
  onClose,
  onSelectStep,
  onEdit
}: {
  definition: FlowDefinition;
  stepKey: string;
  /** Where each step comes from (the flow's `step_origins`). */
  origins?: StepOriginPublic[];
  names?: FlowNames;
  /** What the space can call, so a function step says whether it can run. */
  functions?: FlowFunctionPublic[];
  /** The panel covers the conversation: navigator and two-column rows. */
  wide: boolean;
  onClose: () => void;
  onSelectStep: (key: string) => void;
  /** Enters edit mode on this step; absent without edit permission. */
  onEdit?: () => void;
}) {
  const t = useTranslations();
  const steps = stepsOf(definition);
  const index = steps.findIndex((step) => step.key === stepKey);
  const step = index >= 0 ? steps[index]! : null;
  const previous = index > 0 ? steps[index - 1]! : null;
  const next = index >= 0 && index + 1 < steps.length ? steps[index + 1]! : null;
  const origin = origins.find((entry) => entry.key === stepKey) ?? null;

  if (!step) {
    return (
      <div className="flex flex-col gap-3 p-4">
        <Button
          label={t("flow_step_overview")}
          variant="ghost"
          size="sm"
          icon={<ArrowLeft className="size-4" />}
          onClick={onClose}
          className="self-start"
        />
        <Text type="supporting">{t("flow_step_missing")}</Text>
      </div>
    );
  }

  const pager = (
    <>
      <IconButton
        label={t("flow_step_previous")}
        tooltip={t("flow_step_previous")}
        icon={<ChevronLeft className="size-4" />}
        variant="ghost"
        size="sm"
        isDisabled={previous === null}
        onClick={() => previous && onSelectStep(previous.key)}
      />
      <IconButton
        label={t("flow_step_next")}
        tooltip={t("flow_step_next")}
        icon={<ChevronRight className="size-4" />}
        variant="ghost"
        size="sm"
        isDisabled={next === null}
        onClick={() => next && onSelectStep(next.key)}
      />
    </>
  );

  const main = (
    <div
      className={cn("flex min-w-0 flex-col gap-6", wide ? "mx-auto w-full max-w-4xl p-6" : "p-4")}
    >
      <header className="flex flex-wrap items-start gap-3">
        {!wide && <StepGlyph step={step} index={index} />}
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <Text type="supporting" size="sm">
              {t("flow_step_position", { index: index + 1, count: steps.length })}
            </Text>
            <Badge
              variant={step.kind === "review" ? "orange" : "neutral"}
              label={stepKindLabel(step.kind, t)}
            />
          </div>
          <Heading level={2} className="m-0 text-lg leading-tight font-semibold">
            {step.name}
          </Heading>
          {step.description && (
            <Text type="supporting" as="p" display="block" className="m-0 max-w-prose leading-snug">
              {step.description}
            </Text>
          )}
        </div>
        {wide && (
          <div className="flex items-center gap-1">
            {onEdit && (
              <Button
                label={t("flow_step_edit_flow")}
                variant="secondary"
                size="sm"
                icon={<Pencil className="size-4" />}
                onClick={onEdit}
              />
            )}
            {pager}
          </div>
        )}
      </header>
      <StepSections
        step={step}
        definition={definition}
        names={names}
        functions={functions}
        onSelectStep={onSelectStep}
        wide={wide}
      />
      {!wide && onEdit && (
        <Button
          label={t("flow_step_edit_flow")}
          variant="secondary"
          size="sm"
          icon={<Pencil className="size-4" />}
          onClick={onEdit}
          className="self-start"
        />
      )}
      <TechFooter step={step} origin={origin} />
    </div>
  );

  if (wide) {
    return (
      <div className="@container flex min-h-0 flex-1">
        <FlowStepNav
          definition={definition}
          origins={origins}
          currentKey={step.key}
          onSelect={onSelectStep}
          onOverview={onClose}
        />
        <div className="min-h-0 min-w-0 flex-1 overflow-y-auto">{main}</div>
      </div>
    );
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-ax-border flex shrink-0 items-center gap-1 border-b px-2 py-1">
        <Button
          label={t("flow_step_overview")}
          variant="ghost"
          size="sm"
          icon={<ArrowLeft className="size-4" />}
          onClick={onClose}
        />
        <span className="flex-1" />
        <Text type="supporting" size="sm" hasTabularNumbers>
          {t("flow_step_position", { index: index + 1, count: steps.length })}
        </Text>
        {pager}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">{main}</div>
    </div>
  );
}
