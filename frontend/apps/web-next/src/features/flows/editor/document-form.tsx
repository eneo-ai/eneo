"use client";

import { Button } from "@astryxdesign/core/Button";
import { IconButton } from "@astryxdesign/core/IconButton";
import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { TextInput } from "@/components/astryx/text-input";
import type { FlowNames } from "../flow-step-summary";
import type { DocumentStep, FlowDefinition } from "../types";
import { NameFields, problemStatus, TemplateHint, type FieldProblems } from "./step-fields";
import type { StepDraftState } from "./use-step-draft";

/**
 * The form of a document step: either a Markdown template rendered into a
 * Word or PDF file, or a template file attached in the chat whose fields
 * are filled from values (key → template rows).
 */
export function DocumentForm({
  draft,
  definition,
  names,
  problems
}: {
  draft: StepDraftState;
  definition: FlowDefinition;
  names: FlowNames;
  problems: FieldProblems;
}) {
  const t = useTranslations();
  const step = draft.draft.step as DocumentStep;
  const shape = step.template_file_id ? "template" : "content";
  const values = Object.entries(step.values ?? {});
  const [newKey, setNewKey] = useState("");
  const setValues = (next: [string, string][]) =>
    draft.update({ values: Object.fromEntries(next) });
  const fileName = step.template_file_id ? names.fileName?.(step.template_file_id) : null;
  return (
    <>
      <NameFields step={step} onChange={draft.update} problems={problems} />
      <RadioList
        label={t("flow_editor_document_shape")}
        value={shape}
        onChange={(next) =>
          draft.update(
            next === "template"
              ? { content: null, template_file_id: step.template_file_id ?? "" }
              : { template_file_id: null, values: {} }
          )
        }
      >
        <RadioListItem
          value="content"
          label={t("flow_editor_document_content")}
          description={t("flow_editor_document_content_detail")}
        />
        <RadioListItem
          value="template"
          label={t("flow_editor_document_template")}
          description={t("flow_editor_document_template_detail")}
        />
      </RadioList>
      {shape === "content" ? (
        <div className="flex flex-col gap-1.5">
          <TextArea
            label={t("flow_param_content")}
            value={step.content ?? ""}
            onChange={(content) => draft.update({ content })}
            rows={12}
            isRequired
            status={problemStatus(problems.content)}
            placeholder={t("flow_editor_content_placeholder")}
          />
          <TemplateHint definition={definition} stepKey={step.key} />
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <TextInput
            label={t("flow_param_template_file")}
            description={fileName ?? t("flow_editor_template_file_hint")}
            value={step.template_file_id ?? ""}
            onChange={(template_file_id) => draft.update({ template_file_id })}
            isRequired
            status={problemStatus(problems.template_file_id)}
          />
          <div className="flex flex-col gap-2">
            <Text type="label">{t("flow_param_fields")}</Text>
            <Text type="supporting" size="xsm" as="p" display="block" className="m-0">
              {t("flow_editor_values_hint")}
            </Text>
            {values.map(([key, template], index) => (
              <div key={key} className="flex items-end gap-2">
                <TextInput
                  label={t("flow_editor_value_key")}
                  value={key}
                  isReadOnly
                  size="sm"
                  width={200}
                />
                <TextInput
                  label={t("flow_editor_value_template", { key })}
                  isLabelHidden
                  value={template}
                  onChange={(next) =>
                    setValues(values.map((entry, at) => (at === index ? [key, next] : entry)))
                  }
                  size="sm"
                  width="100%"
                />
                <IconButton
                  label={t("flow_editor_value_remove", { key })}
                  tooltip={t("remove")}
                  icon={<Trash2 className="size-4" />}
                  variant="ghost"
                  size="sm"
                  onClick={() => setValues(values.filter((_, at) => at !== index))}
                />
              </div>
            ))}
            <div className="flex items-end gap-2">
              <TextInput
                label={t("flow_editor_value_new")}
                value={newKey}
                onChange={setNewKey}
                size="sm"
                width={200}
                placeholder={t("flow_editor_value_new_placeholder")}
                onEnter={() => {
                  if (newKey.trim()) {
                    setValues([...values, [newKey.trim(), "{{previous}}"]]);
                    setNewKey("");
                  }
                }}
              />
              <Button
                label={t("flow_editor_value_add")}
                size="sm"
                icon={<Plus className="size-4" />}
                isDisabled={!newKey.trim() || values.some(([key]) => key === newKey.trim())}
                onClick={() => {
                  setValues([...values, [newKey.trim(), "{{previous}}"]]);
                  setNewKey("");
                }}
              />
            </div>
            {problems.values && (
              <Text type="supporting" size="xsm" className="text-ax-error">
                {problems.values}
              </Text>
            )}
          </div>
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-3">
        {shape === "content" && (
          <Selector
            label={t("flow_param_format")}
            options={[
              { value: "docx", label: t("flow_produces_docx") },
              { value: "pdf", label: t("flow_produces_pdf") }
            ]}
            value={step.format ?? "docx"}
            onChange={(format) => draft.update({ format: format === "pdf" ? "pdf" : "docx" })}
            status={problemStatus(problems.format)}
          />
        )}
        <TextInput
          label={t("title")}
          value={step.title ?? ""}
          onChange={(title) => draft.update({ title: title || null })}
          placeholder={t("flow_param_title_default")}
          status={problemStatus(problems.title)}
        />
        <TextInput
          label={t("flow_param_filename")}
          value={step.filename ?? ""}
          onChange={(filename) => draft.update({ filename: filename || null })}
          placeholder={t("flow_param_filename_default")}
          status={problemStatus(problems.filename)}
        />
      </div>
    </>
  );
}
