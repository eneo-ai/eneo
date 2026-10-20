"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { Chip, Field, MonoBlock } from "./flow-fields";
import { formatDuration, stepKindLabel } from "./flow-labels";
import { TemplateText } from "./flow-template";
import type {
  DocumentStep,
  FlowDefinition,
  FlowStep,
  LlmStep,
  ReviewStep,
  TranscribeStep
} from "./types";

/**
 * Names for the ids a definition carries. The panel builds one from the
 * space (its models and knowledge); without it the ids show as they are.
 */
export type FlowNames = {
  modelName?: (id: string) => string | null;
  transcriptionModelName?: (id: string) => string | null;
  collectionName?: (id: string) => string | null;
  websiteName?: (id: string) => string | null;
  fileName?: (id: string) => string | null;
};

const NO_NAMES: FlowNames = {};

const shortId = (id: string) => (id.length > 12 ? `${id.slice(0, 8)}…` : id);

function Named({ id, resolve }: { id: string; resolve?: (id: string) => string | null }) {
  const name = resolve?.(id) ?? null;
  return name ? <>{name}</> : <span className="font-mono text-xs">{shortId(id)}</span>;
}

function ChipList({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap gap-1">{children}</div>;
}

/** The property names a JSON schema asks for at its top level, in order. */
export function schemaFieldNames(schema: Record<string, unknown>): string[] {
  const properties = schema.properties;
  if (!properties || typeof properties !== "object") return [];
  return Object.keys(properties as Record<string, unknown>);
}

function formLabel(definition: FlowDefinition, key: string): string {
  return definition.form_fields.find((field) => field.key === key)?.label ?? key;
}

function stepName(definition: FlowDefinition, key: string, t: ReturnType<typeof useTranslations>) {
  const index = definition.steps.findIndex((step) => step.key === key);
  if (index < 0) return key;
  return `${t("flow_ref_step", { index: index + 1 })} · ${definition.steps[index]!.name}`;
}

function LlmFields({
  step,
  definition,
  names
}: {
  step: LlmStep;
  definition: FlowDefinition;
  names: FlowNames;
}) {
  const t = useTranslations();
  const knowledge = step.knowledge ?? {};
  const collections = knowledge.collection_ids ?? [];
  const websites = knowledge.website_ids ?? [];
  const files = step.files_from ?? [];
  const output = step.output ?? { type: "text" };
  const kwargs = Object.entries(step.model_kwargs ?? {}).filter(([, value]) => value != null);
  return (
    <>
      <Field label={t("flow_param_prompt")}>
        <MonoBlock>{step.prompt}</MonoBlock>
      </Field>
      <Field label={t("flow_param_input")}>
        <MonoBlock>
          <TemplateText template={step.input ?? "{{previous}}"} definition={definition} />
        </MonoBlock>
      </Field>
      <Field label={t("model")}>
        {step.model_id ? (
          <Named id={step.model_id} resolve={names.modelName} />
        ) : (
          t("flow_param_model_default")
        )}
        {kwargs.length > 0 && (
          <span className="text-ax-text-secondary">
            {" · "}
            {kwargs.map(([key, value]) => `${key}: ${String(value)}`).join(" · ")}
          </span>
        )}
      </Field>
      <Field label={t("knowledge")}>
        {collections.length === 0 && websites.length === 0 ? (
          t("flow_param_none")
        ) : (
          <ChipList>
            {collections.map((id) => (
              <Chip key={id}>
                <Named id={id} resolve={names.collectionName} />
              </Chip>
            ))}
            {websites.map((id) => (
              <Chip key={id}>
                <Named id={id} resolve={names.websiteName} />
              </Chip>
            ))}
          </ChipList>
        )}
      </Field>
      <Field label={t("flow_param_files")}>
        {files.length === 0 ? (
          t("flow_param_none")
        ) : (
          <ChipList>
            {files.map((key) => (
              <Chip key={key} tone="accent">
                {t("flow_ref_input")} · {formLabel(definition, key)}
              </Chip>
            ))}
          </ChipList>
        )}
      </Field>
      <Field label={t("output")}>
        {output.type === "json" ? (
          <div className="flex flex-col gap-1.5">
            <span>
              {t("flow_param_output_json")}
              {schemaFieldNames(output.schema).length > 0 && (
                <>
                  {": "}
                  <span className="font-mono text-xs">
                    {schemaFieldNames(output.schema).join(", ")}
                  </span>
                </>
              )}
            </span>
            <MonoBlock>{JSON.stringify(output.schema, null, 2)}</MonoBlock>
          </div>
        ) : (
          t("flow_param_output_text")
        )}
      </Field>
    </>
  );
}

function DocumentFields({
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
    <>
      {step.template_file_id ? (
        <Field label={t("flow_param_template_file")}>
          <Named id={step.template_file_id} resolve={names.fileName} />
        </Field>
      ) : (
        <Field label={t("flow_param_content")}>
          <MonoBlock>
            <TemplateText template={step.content ?? ""} definition={definition} />
          </MonoBlock>
        </Field>
      )}
      {values.length > 0 && (
        <Field label={t("flow_param_fields")}>
          <dl className="m-0 flex flex-col gap-1">
            {values.map(([name, template]) => (
              <div key={name} className="flex flex-wrap items-baseline gap-x-2">
                <dt className="font-mono text-xs">{name}</dt>
                <dd className="m-0 min-w-0">
                  <span aria-hidden="true" className="text-ax-text-secondary">
                    ←{" "}
                  </span>
                  <TemplateText template={template} definition={definition} />
                </dd>
              </div>
            ))}
          </dl>
        </Field>
      )}
      {step.title && (
        <Field label={t("title")}>
          <TemplateText template={step.title} definition={definition} />
        </Field>
      )}
      <Field label={t("flow_param_format")}>{(step.format ?? "docx").toUpperCase()}</Field>
      <Field label={t("flow_param_filename")}>
        {step.filename ? (
          <TemplateText template={step.filename} definition={definition} />
        ) : (
          t("flow_param_filename_default")
        )}
      </Field>
    </>
  );
}

function ReviewFields({ step, definition }: { step: ReviewStep; definition: FlowDefinition }) {
  const t = useTranslations();
  const index = definition.steps.findIndex((candidate) => candidate.key === step.key);
  const targetKey = step.of ?? (index > 0 ? definition.steps[index - 1]!.key : null);
  return (
    <>
      <Field label={t("flow_param_review_mode")}>
        {(step.mode ?? "edit") === "edit"
          ? t("flow_param_review_mode_edit")
          : t("flow_param_review_mode_view")}
      </Field>
      <Field label={t("flow_param_reviews")}>
        {targetKey ? stepName(definition, targetKey, t) : t("flow_param_none")}
      </Field>
      <Field label={t("flow_param_time_limit")}>
        {step.expires_after_seconds
          ? t("flow_param_time_limit_value", {
              duration: formatDuration(step.expires_after_seconds, t)
            })
          : t("flow_param_time_limit_none")}
      </Field>
    </>
  );
}

function TranscribeFields({
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
  const speakers = step.speaker_labels
    ? [
        step.max_speakers
          ? t("flow_param_speakers_max", { count: step.max_speakers })
          : t("flow_param_speakers_on"),
        mapping?.participants_field
          ? t("flow_param_speakers_from", {
              field: formLabel(definition, mapping.participants_field)
            })
          : mapping?.infer_names
            ? t("flow_param_speakers_infer")
            : null
      ]
        .filter(Boolean)
        .join(" · ")
    : t("flow_param_speakers_off");
  return (
    <>
      <Field label={t("flow_param_source")}>
        <Chip tone="accent">
          {t("flow_ref_input")} · {formLabel(definition, step.source)}
        </Chip>
      </Field>
      <Field label={t("model")}>
        {step.transcription_model_id ? (
          <Named id={step.transcription_model_id} resolve={names.transcriptionModelName} />
        ) : (
          t("flow_param_model_default")
        )}
      </Field>
      <Field label={t("language")}>{step.language ?? t("flow_param_language_auto")}</Field>
      <Field label={t("flow_param_speakers")}>{speakers}</Field>
    </>
  );
}

/**
 * One step of a flow, always expanded, every parameter visible and none
 * editable: the chat is where a flow changes. Templates show their
 * `{{…}}` references as badges naming the step or input they read.
 */
export function FlowStepCard({
  step,
  index,
  definition,
  names = NO_NAMES
}: {
  step: FlowStep;
  index: number;
  definition: FlowDefinition;
  names?: FlowNames;
}) {
  const t = useTranslations();
  const kind = stepKindLabel(step.kind, t);
  return (
    <article
      aria-label={t("flow_step_label", { index: index + 1, name: step.name })}
      className="border-ax-border bg-ax-card rounded-ax-container flex flex-col gap-3 border p-3"
    >
      <header className="flex items-center gap-2">
        <span
          aria-hidden="true"
          className="bg-ax-muted text-ax-text-secondary flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold tabular-nums"
        >
          {index + 1}
        </span>
        <h4 className="min-w-0 flex-1 truncate text-sm font-semibold">{step.name}</h4>
        <Badge variant="neutral" label={kind} />
      </header>
      {step.description && (
        <p className="text-ax-text-secondary m-0 text-[13px]">{step.description}</p>
      )}
      <dl className="m-0 flex flex-col gap-2.5">
        {step.kind === "llm" && <LlmFields step={step} definition={definition} names={names} />}
        {step.kind === "compose" && (
          <Field label={t("flow_param_template")}>
            <MonoBlock>
              <TemplateText template={step.template} definition={definition} />
            </MonoBlock>
          </Field>
        )}
        {step.kind === "document" && (
          <DocumentFields step={step} definition={definition} names={names} />
        )}
        {step.kind === "review" && <ReviewFields step={step} definition={definition} />}
        {step.kind === "transcribe" && (
          <TranscribeFields step={step} definition={definition} names={names} />
        )}
      </dl>
    </article>
  );
}
