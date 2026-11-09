import { Button } from "@astryxdesign/core/Button";
import { FileInput } from "@astryxdesign/core/FileInput";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useFormatter, useTranslations } from "use-intl";
import { useState } from "react";
import { Collapsible } from "@/components/astryx/collapsible";
import { ListError } from "@/components/composites/query-state";
import { LoadingState } from "@/components/composites/loading-state";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { DownloadButton } from "../runs/run-files";
import {
  flowEditorKeys,
  inspectTemplate,
  templateDownloadPath,
  templateFilesQueryOptions,
  templateInspectionQueryOptions,
  uploadTemplate
} from "./editor-api";
import { problemStatus } from "./editor-fields";
import { useRecordUpload } from "./editor-uploads";
import { describeSaveError } from "./field-problems";
import {
  isStructuredTemplateBinding,
  readTemplateFill,
  withTemplate,
  withTemplateBinding
} from "./step-configs";
import {
  invalidOptionLabel,
  meaningLabel,
  stepLabel,
  variableEntryLabel,
  variableGroupTitle
} from "./step-labels";
import { readMeaning } from "./request-preview";
import {
  bindsTemplateField,
  fillsTemplateField,
  templateBindingListField,
  templateBindingToken
} from "./step-rules";
import type { FlowPublic, JsonObject, StepConfig, TemplateInspection } from "./step-types";
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
      if (!fillsTemplateField(entry)) continue;
      const name =
        entry.kind.type === "field"
          ? entry.kind.label
          : entry.kind.type === "date"
            ? entry.token
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

type Translate = ReturnType<typeof useTranslations>;

/**
 * What a field can be filled with, by group, and how each source reads once
 * chosen (`chosen`): an earlier step's answer names its step, as a reference
 * pill does (`meaningLabel`), since several steps can answer in text.
 */
function bindingSources(groups: VariableGroup[], t: Translate) {
  const chosen = new Map<string, string>();
  const sections = groups.flatMap((group) => {
    const options = group.entries.filter(fillsTemplateField).map((entry) => {
      const value = `{{${entry.token}}}`;
      const label = variableEntryLabel(entry, t);
      chosen.set(
        value,
        group.type === "step"
          ? t("flows_chat_reference_value", {
              step: stepLabel(group.stepOrder, group.stepName, t),
              what:
                entry.kind.type === "step_field"
                  ? entry.kind.field
                  : t("flows_chat_reference_value_text")
            })
          : label
      );
      return { value, label };
    });
    if (options.length === 0) return [];
    return [{ type: "section" as const, title: variableGroupTitle(group, t), options }];
  });
  return { sections, chosen };
}

/** How many of a template's fields have a value the flow has: "" (left empty) counts. */
function boundCount(
  placeholders: string[],
  bindings: Record<string, string>,
  binds: (binding: string) => boolean
): number {
  return placeholders.filter((name) => {
    const binding = bindings[name];
    return binding === "" || (binding !== undefined && binds(binding));
  }).length;
}

function fieldsCountText(bound: number, total: number, t: Translate): string {
  return bound === total
    ? t("flow_step_editor_template_fields_count", { total })
    : t("flow_step_editor_template_fields_todo", { bound, total });
}

/**
 * The Word template a template step fills and what goes into each of its
 * fields. Uploading a template adds it to the flow at once; choosing it for
 * the step is part of the draft. The chosen template can be downloaded.
 */
export function TemplateFillFields({
  flow,
  stepOrder,
  draft,
  onChange,
  groups,
  problem
}: {
  flow: Pick<FlowPublic, "id" | "steps" | "metadata_json">;
  stepOrder: number;
  draft: StepConfig;
  onChange: (outputConfig: JsonObject | null) => void;
  groups: VariableGroup[];
  problem?: string;
}) {
  const flowId = flow.id;
  const binds = (binding: string) => bindsTemplateField(binding, stepOrder, flow);
  const t = useTranslations();
  const format = useFormatter();
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const files = useQuery(templateFilesQueryOptions(flowId));
  const config = readTemplateFill(draft.output_config);
  const inspection = useQuery({
    ...templateInspectionQueryOptions(flowId, config.templateAssetId ?? ""),
    enabled: config.templateAssetId !== null
  });
  // Which control is working: the picker's choice or an upload.
  const [busy, setBusy] = useState<"select" | "upload" | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  // The file on its way up, or the one refused, so its name stays beside what happened.
  const [picked, setPicked] = useState<File | null>(null);
  const [uploadFailure, setUploadFailure] = useState<string | null>(null);
  const recordUpload = useRecordUpload();

  /** Chooses the template for the step; returns how many of its fields are ready. */
  function choose(result: TemplateInspection, assetId: string): number {
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
    return boundCount(placeholders, readTemplateFill(next).bindings, binds);
  }

  async function select(assetId: string | null) {
    setFailure(null);
    // A refused upload is over once the author chooses from the list instead.
    setPicked(null);
    setUploadFailure(null);
    if (!assetId) {
      onChange(withTemplate(draft.output_config, null));
      return;
    }
    setBusy("select");
    try {
      const result = await queryClient.query(templateInspectionQueryOptions(flowId, assetId));
      choose(result, assetId);
    } catch (error) {
      setFailure(describeError(error));
    } finally {
      setBusy(null);
    }
  }

  function describeError(error: unknown): string {
    return describeSaveError(error, { stepId: "", stepOrder: 0, config: draft }, t).message;
  }

  async function upload(chosenFiles: File | File[] | null) {
    const file = Array.isArray(chosenFiles) ? (chosenFiles[0] ?? null) : chosenFiles;
    if (busy) return;
    setPicked(file);
    setUploadFailure(null);
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".docx")) {
      setUploadFailure(t("flow_error_flow_template_unsupported_extension"));
      return;
    }
    setBusy("upload");
    try {
      const asset = await uploadTemplate(flowId, file);
      recordUpload({ kind: "template", id: asset.id });
      await queryClient.invalidateQueries({ queryKey: flowEditorKeys.templateFiles(flowId) });
      const result = await inspectTemplate(flowId, asset.id);
      queryClient.setQueryData(flowEditorKeys.templateInspection(flowId, asset.id), result);
      const ready = choose(result, asset.id);
      setPicked(null);
      const uploaded = t("flow_step_editor_template_uploaded", { name: asset.name });
      const total = result.placeholders.length;
      announce(total > 0 ? `${uploaded} ${fieldsCountText(ready, total, t)}` : uploaded);
    } catch (error) {
      setUploadFailure(describeError(error));
    } finally {
      setBusy(null);
    }
  }

  if (files.isPending)
    return <LoadingState label={t("flow_step_editor_templates_loading")} rows={2} />;
  if (files.isError) return <ListError error={files.error} onRetry={() => void files.refetch()} />;

  const assets = files.data;
  const chosen = assets.find((asset) => asset.id === config.templateAssetId);
  const missing = config.templateAssetId !== null && !chosen;
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
  const sources = bindingSources(groups, t);
  const bound = boundCount(
    placeholders.map((placeholder) => placeholder.name),
    config.bindings,
    binds
  );
  // A flow without templates starts at the upload; the picker comes with the first one.
  const hasPicker = assets.length > 0 || config.templateAssetId !== null;

  return (
    <div className="flex flex-col gap-4">
      {hasPicker ? (
        <Selector
          label={t("flow_step_editor_template")}
          description={t("flow_step_editor_template_description")}
          options={[
            { value: UNBOUND, label: t("flow_step_editor_template_none") },
            ...assets.map((asset) => ({
              value: asset.id,
              label: asset.name,
              // Two uploads of one file share a name: when each came tells them apart.
              description: asset.created_at
                ? t("flow_step_editor_template_uploaded_on", {
                    date: format.dateTime(new Date(asset.created_at), {
                      dateStyle: "medium",
                      timeStyle: "short"
                    })
                  })
                : undefined,
              disabled: asset.can_select === false && asset.id !== config.templateAssetId
            })),
            ...(missing && config.templateAssetId
              ? [
                  {
                    value: config.templateAssetId,
                    label: invalidOptionLabel(
                      config.templateName ?? t("flow_step_editor_template_missing"),
                      t
                    )
                  }
                ]
              : [])
          ]}
          value={config.templateAssetId ?? UNBOUND}
          onChange={(value) => void select(value === UNBOUND ? null : value)}
          isLoading={busy === "select"}
          status={problemStatus(
            failure ?? problem ?? (missing ? t("flow_step_editor_template_missing_help") : null)
          )}
          width="100%"
        />
      ) : null}
      {chosen?.can_download ? (
        <div>
          <DownloadButton
            label={t("flow_runs_file_download", { name: chosen.name })}
            visible={t("flow_runs_file_download_short")}
            getPath={() => templateDownloadPath(flowId, chosen)}
            name={chosen.name}
          />
        </div>
      ) : null}
      {inspection.isError && config.templateAssetId && (
        <ListError error={inspection.error} onRetry={() => void inspection.refetch()} />
      )}

      {/* The fields of a template that is gone are not the author's to fill. */}
      {config.templateAssetId && !missing && placeholders.length > 0 && (
        <fieldset className="m-0 flex min-w-0 flex-col gap-4 border-0 p-0">
          <legend className="mb-1 p-0">
            <Text type="label">{t("flow_step_editor_template_fields")}</Text>
          </legend>
          {/* Read out as it changes: the author's focus stays on the field they chose for. */}
          <div role="status" aria-atomic="true">
            <Text type="supporting" size="sm" as="p" display="block" className="m-0">
              {fieldsCountText(bound, placeholders.length, t)}
            </Text>
          </div>
          {placeholders.map((placeholder) => {
            const binding = config.bindings[placeholder.name];
            const unknown = binding !== undefined && binding !== "" && !binds(binding);
            // A list or multiple-choice field holds several values; a Word field takes one.
            const list = unknown ? templateBindingListField(binding, flow) : null;
            // A binding written otherwise than the picker writes it (`{{ datum }}`) shows as
            // the choice it reads; one the picker does not offer (`{{föregående_steg}}`) as
            // what it reads, never as code.
            const token = binding ? templateBindingToken(binding) : null;
            const offered =
              token !== null && sources.chosen.has(`{{${token}}}`) ? `{{${token}}}` : null;
            const unlisted =
              binding && token !== null && !unknown && offered === null
                ? {
                    value: binding,
                    label: meaningLabel(readMeaning(token, stepOrder, flow), token, flow, t)
                  }
                : null;
            return (
              <Selector
                key={placeholder.name}
                label={placeholder.label || placeholder.name}
                description={placeholder.hint ?? undefined}
                placeholder={t("flow_step_editor_template_field_unbound")}
                options={[
                  { value: EMPTY, label: t("flow_step_editor_template_field_empty") },
                  // The reference itself is code; the author sees only that the choice is gone.
                  ...(unknown
                    ? [
                        {
                          value: binding,
                          label: list ? list.label : t("flow_step_editor_template_field_gone")
                        }
                      ]
                    : []),
                  ...(unlisted ? [unlisted] : []),
                  ...sources.sections
                ]}
                value={
                  binding === undefined ? undefined : binding === "" ? EMPTY : (offered ?? binding)
                }
                renderValue={(option) => sources.chosen.get(option.value) ?? option.label}
                onChange={(next) =>
                  onChange(
                    withTemplateBinding(
                      draft.output_config,
                      placeholder.name,
                      next === EMPTY ? "" : next
                    )
                  )
                }
                status={
                  binding && isStructuredTemplateBinding(binding)
                    ? { type: "error", message: t("flow_template_fill_json_warning") }
                    : list
                      ? { type: "error", message: t("flow_step_editor_template_field_list") }
                      : unknown
                        ? { type: "error", message: t("flow_step_editor_template_field_unknown") }
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

      <FileInput
        label={
          config.templateAssetId
            ? t("flow_step_editor_template_upload")
            : t("flow_step_editor_template_upload_first")
        }
        description={t("flow_step_editor_template_upload_description")}
        value={picked}
        onChange={(chosenFiles) => void upload(chosenFiles)}
        accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        isLoading={busy === "upload"}
        status={problemStatus(uploadFailure ?? (hasPicker ? null : problem))}
        width="100%"
      />
      <TemplateGuide defaultIsOpen={!hasPicker} />
    </div>
  );
}

/** How to make a Word file the step can fill: what a first template needs. */
function TemplateGuide({ defaultIsOpen }: { defaultIsOpen: boolean }) {
  const t = useTranslations();
  return (
    <Collapsible
      defaultIsOpen={defaultIsOpen}
      chevronPosition="start"
      trigger={<Text type="label">{t("flow_step_editor_template_guide_title")}</Text>}
    >
      <ol className="text-ax-text-secondary m-0 flex max-w-prose list-decimal flex-col gap-1 ps-5 text-sm">
        <li>{t("flow_step_editor_template_guide_developer")}</li>
        <li>{t("flow_step_editor_template_guide_control")}</li>
        <li>{t("flow_step_editor_template_guide_tag")}</li>
        <li>{t("flow_step_editor_template_guide_save")}</li>
      </ol>
    </Collapsible>
  );
}
