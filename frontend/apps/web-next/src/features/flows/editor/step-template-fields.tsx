"use client";

import { Button } from "@astryxdesign/core/Button";
import { FileInput } from "@astryxdesign/core/FileInput";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useTranslations } from "use-intl";
import { useState } from "react";
import { ListError } from "@/components/composites/query-state";
import { LoadingState } from "@/components/composites/loading-state";
import { useAnnounce } from "@astryxdesign/core/hooks";
import {
  flowEditorKeys,
  inspectTemplate,
  templateFilesQueryOptions,
  templateInspectionQueryOptions,
  uploadTemplate
} from "./editor-api";
import { FieldMessage, problemStatus } from "./editor-fields";
import { useRecordUpload } from "./editor-uploads";
import { describeSaveError } from "./field-problems";
import {
  isStructuredTemplateBinding,
  readTemplateFill,
  withTemplate,
  withTemplateBinding
} from "./step-configs";
import { stepLabel } from "./step-labels";
import type { JsonObject, StepConfig, TemplateInspection } from "./step-types";
import type { VariableGroup } from "./step-variables";

const UNBOUND = "__unbound";
const EMPTY = "__empty";

/** Placeholder names whose words match one source, bound before the author chooses. */
export function suggestedBindings(
  placeholders: string[],
  groups: VariableGroup[]
): Record<string, string> {
  const normalise = (value: string) =>
    value
      .normalize("NFKD")
      .replace(/\p{M}/gu, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "");
  const sources = new Map<string, string | null>();
  for (const group of groups) {
    for (const entry of group.entries) {
      const name =
        entry.kind.type === "field"
          ? entry.kind.label
          : group.type === "step" && entry.kind.type === "step_text"
            ? group.stepName
            : null;
      if (!name) continue;
      const key = normalise(name);
      sources.set(key, sources.has(key) ? null : `{{${entry.token}}}`);
    }
  }
  const result: Record<string, string> = {};
  for (const placeholder of placeholders) {
    const match = sources.get(normalise(placeholder));
    if (match) result[placeholder] = match;
  }
  return result;
}

function bindingOptions(groups: VariableGroup[], t: ReturnType<typeof useTranslations>) {
  return groups.flatMap((group) => {
    const options = group.entries
      .filter((entry) => !isStructuredTemplateBinding(`{{${entry.token}}}`))
      .map((entry) => ({
        value: `{{${entry.token}}}`,
        label:
          entry.kind.type === "field"
            ? entry.kind.label
            : entry.kind.type === "step_field"
              ? entry.kind.field
              : entry.kind.type === "date"
                ? t("flow_step_editor_variable_date")
                : entry.kind.type === "step_text"
                  ? t("flow_step_editor_variable_step_text")
                  : entry.token,
        description: `{{${entry.token}}}`
      }));
    if (options.length === 0) return [];
    return [
      {
        type: "section" as const,
        title:
          group.type === "fields"
            ? t("flow_step_editor_variables_fields")
            : group.type === "run"
              ? t("flow_step_editor_variables_run")
              : stepLabel(group.stepOrder, group.stepName, t),
        options
      }
    ];
  });
}

/**
 * The Word template a template step fills and what goes into each of its
 * fields. Uploading a template adds it to the flow at once; choosing it for
 * the step is part of the draft.
 */
export function TemplateFillFields({
  flowId,
  draft,
  onChange,
  groups,
  problem
}: {
  flowId: string;
  draft: StepConfig;
  onChange: (outputConfig: JsonObject | null) => void;
  groups: VariableGroup[];
  problem?: string;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const files = useQuery(templateFilesQueryOptions(flowId));
  const config = readTemplateFill(draft.output_config);
  const inspection = useQuery({
    ...templateInspectionQueryOptions(flowId, config.templateAssetId ?? ""),
    enabled: config.templateAssetId !== null
  });
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const recordUpload = useRecordUpload();

  function choose(result: TemplateInspection, assetId: string) {
    const placeholders = result.placeholders.map((item) => item.name);
    let next = withTemplate(draft.output_config, {
      assetId,
      name: result.file_name,
      placeholders
    });
    const current = readTemplateFill(next);
    for (const [placeholder, binding] of Object.entries(suggestedBindings(placeholders, groups))) {
      if (!(placeholder in current.bindings))
        next = withTemplateBinding(next, placeholder, binding);
    }
    onChange(next);
  }

  async function select(assetId: string | null) {
    setFailure(null);
    if (!assetId) {
      onChange(withTemplate(draft.output_config, null));
      return;
    }
    setBusy(true);
    try {
      const result = await queryClient.query(templateInspectionQueryOptions(flowId, assetId));
      choose(result, assetId);
    } catch (error) {
      setFailure(describeError(error));
    } finally {
      setBusy(false);
    }
  }

  function describeError(error: unknown): string {
    return describeSaveError(error, { stepId: "", stepOrder: 0, config: draft }, t).message;
  }

  async function upload(picked: File | File[] | null) {
    const file = Array.isArray(picked) ? picked[0] : picked;
    if (!file || busy) return;
    setFailure(null);
    if (!file.name.toLowerCase().endsWith(".docx")) {
      setFailure(t("flow_error_flow_template_unsupported_extension"));
      return;
    }
    setBusy(true);
    try {
      const asset = await uploadTemplate(flowId, file);
      recordUpload({ kind: "template", id: asset.id });
      await queryClient.invalidateQueries({ queryKey: flowEditorKeys.templateFiles(flowId) });
      const result = await inspectTemplate(flowId, asset.id);
      queryClient.setQueryData(flowEditorKeys.templateInspection(flowId, asset.id), result);
      choose(result, asset.id);
      announce(t("flow_step_editor_template_uploaded", { name: asset.name }));
    } catch (error) {
      setFailure(describeError(error));
    } finally {
      setBusy(false);
    }
  }

  if (files.isPending)
    return <LoadingState label={t("flow_step_editor_templates_loading")} rows={2} />;
  if (files.isError) return <ListError error={files.error} onRetry={() => void files.refetch()} />;

  const assets = files.data;
  const placeholders =
    inspection.data?.placeholders ??
    config.placeholders.map((name) => ({
      name,
      label: name,
      kind: "text" as const,
      location: "",
      hint: null
    }));
  const orphaned = Object.keys(config.bindings).filter(
    (name) => !placeholders.some((placeholder) => placeholder.name === name)
  );
  const bound = placeholders.filter((placeholder) => placeholder.name in config.bindings).length;
  const options = bindingOptions(groups, t);

  return (
    <div className="flex flex-col gap-4">
      <Selector
        label={t("flow_step_editor_template")}
        description={t("flow_step_editor_template_description")}
        options={[
          { value: UNBOUND, label: t("flow_step_editor_template_none") },
          ...assets.map((asset) => ({
            value: asset.id,
            label: asset.name,
            disabled: asset.can_select === false && asset.id !== config.templateAssetId
          })),
          ...(config.templateAssetId && !assets.some((asset) => asset.id === config.templateAssetId)
            ? [
                {
                  value: config.templateAssetId,
                  label: config.templateName ?? t("flow_step_editor_template_missing")
                }
              ]
            : [])
        ]}
        value={config.templateAssetId ?? UNBOUND}
        onChange={(value) => void select(value === UNBOUND ? null : value)}
        isLoading={busy}
        status={problemStatus(problem)}
        width="100%"
      />
      <FileInput
        label={t("flow_step_editor_template_upload")}
        description={t("flow_step_editor_template_upload_description")}
        value={null}
        onChange={(picked) => void upload(picked)}
        accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        isLoading={busy}
      />
      <FieldMessage message={failure} />
      {inspection.isError && config.templateAssetId && (
        <ListError error={inspection.error} onRetry={() => void inspection.refetch()} />
      )}

      {config.templateAssetId && placeholders.length > 0 && (
        <fieldset className="m-0 flex min-w-0 flex-col gap-4 border-0 p-0">
          <legend className="mb-2 p-0">
            <Text type="label">{t("flow_step_editor_template_fields")}</Text>
          </legend>
          <Text type="supporting" size="sm" as="p" display="block" className="m-0">
            {t("flow_step_editor_template_fields_count", { bound, total: placeholders.length })}
          </Text>
          {placeholders.map((placeholder) => {
            const binding = config.bindings[placeholder.name];
            const known = options.some((section) =>
              section.options.some((option) => option.value === binding)
            );
            const value = binding === undefined ? UNBOUND : binding === "" ? EMPTY : binding;
            return (
              <Selector
                key={placeholder.name}
                label={placeholder.label || placeholder.name}
                description={placeholder.hint ?? undefined}
                options={[
                  { value: UNBOUND, label: t("flow_step_editor_template_field_unbound") },
                  { value: EMPTY, label: t("flow_step_editor_template_field_empty") },
                  ...(binding && !known ? [{ value: binding, label: binding }] : []),
                  ...options
                ]}
                value={value}
                hasSearch={options.length > 0}
                onChange={(next) =>
                  onChange(
                    withTemplateBinding(
                      draft.output_config,
                      placeholder.name,
                      next === UNBOUND ? null : next === EMPTY ? "" : next
                    )
                  )
                }
                status={
                  binding && isStructuredTemplateBinding(binding)
                    ? { type: "error", message: t("flow_template_fill_json_warning") }
                    : binding === undefined
                      ? { type: "warning", message: t("flow_step_editor_template_field_missing") }
                      : undefined
                }
                width="100%"
              />
            );
          })}
        </fieldset>
      )}

      {orphaned.length > 0 && (
        <div className="flex flex-col gap-2">
          <Text type="supporting" size="sm" as="p" display="block" className="m-0">
            {t("flow_step_editor_template_orphaned")}
          </Text>
          <ul className="m-0 flex list-none flex-col gap-1 p-0">
            {orphaned.map((name) => (
              <li key={name} className="flex flex-wrap items-center gap-2">
                <Text type="code" size="xsm">
                  {name}
                </Text>
                <Button
                  label={t("flow_step_editor_template_orphaned_remove", { name })}
                  variant="ghost"
                  size="sm"
                  icon={<Trash2 className="size-4" aria-hidden="true" />}
                  onClick={() => onChange(withTemplateBinding(draft.output_config, name, null))}
                />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
