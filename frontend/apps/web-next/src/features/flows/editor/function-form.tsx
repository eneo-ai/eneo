"use client";

import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { useTranslations } from "next-intl";
import { TextInput } from "@/components/astryx/text-input";
import {
  functionAvailability,
  functionOf,
  toolArgumentNames,
  toolArgumentSkeleton
} from "../flow-functions";
import { functionPurposeLabel } from "../flow-labels";
import type { FlowDefinition, FlowFunctionPublic, FunctionStep } from "../types";
import {
  FilesFromField,
  JsonTextField,
  NameFields,
  problemStatus,
  TemplateHint,
  type FieldProblems
} from "./step-fields";
import type { StepDraftState } from "./use-step-draft";

const PURPOSES: FunctionStep["purpose"][] = [
  "web_search",
  "image_generation",
  "file_analysis",
  "file_creation",
  "charts",
  "compute"
];

/** Why a purpose cannot be picked now, as the option's description. */
function purposeNote(
  entry: FlowFunctionPublic | null,
  t: ReturnType<typeof useTranslations>
): string | undefined {
  if (!entry) return undefined;
  if (!entry.enabled_in_space) return t("flow_function_disabled");
  if (!entry.available) return t("flow_function_unavailable");
  return entry.provider ?? undefined;
}

/**
 * The form of a function step: the function and tool (from what the space
 * reaches, with the reason when a purpose cannot run), its arguments as
 * JSON with the tool's argument names as a hint, and the files it may read.
 */
export function FunctionForm({
  draft,
  definition,
  functions,
  problems
}: {
  draft: StepDraftState;
  definition: FlowDefinition;
  /** What the space can call; undefined while loading (every purpose is then offered). */
  functions?: FlowFunctionPublic[];
  problems: FieldProblems;
}) {
  const t = useTranslations();
  const step = draft.draft.step as FunctionStep;
  const entry = functionOf(functions, step.purpose);
  const tools = entry?.tools ?? [];
  const tool = tools.find((candidate) => candidate.name === step.tool) ?? null;
  const availability = functionAvailability(functions, step);
  const argumentNames = toolArgumentNames(tool);
  const chooseTool = (name: string) => {
    draft.update({ tool: name });
    // A tool just picked gets its required arguments as a start, unless some are set.
    const chosen = tools.find((candidate) => candidate.name === name) ?? null;
    if (chosen && draft.draft.json.arguments.text.replace(/\s/g, "") in { "{}": 1, "": 1 }) {
      draft.setJson("arguments", JSON.stringify(toolArgumentSkeleton(chosen), null, 2));
    }
  };
  return (
    <>
      <NameFields step={step} onChange={draft.update} problems={problems} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Selector
          label={t("flow_param_function")}
          options={PURPOSES.map((purpose) => {
            const candidate = functionOf(functions, purpose);
            return {
              value: purpose,
              label: functionPurposeLabel(purpose, t),
              description: purposeNote(candidate, t),
              disabled:
                candidate !== null && !candidate.enabled_in_space && purpose !== step.purpose
            };
          })}
          value={step.purpose}
          onChange={(purpose) => draft.update({ purpose: purpose as FunctionStep["purpose"] })}
          status={problemStatus(
            problems.purpose ??
              (availability === "disabled"
                ? t("flow_function_disabled")
                : availability === "unavailable"
                  ? t("flow_function_unavailable")
                  : undefined)
          )}
        />
        {tools.length > 0 ? (
          <Selector
            label={t("flow_editor_tool")}
            description={entry?.provider ?? undefined}
            options={tools.map((candidate) => ({
              value: candidate.name,
              label: candidate.name,
              description: (candidate.description ?? "").split("\n")[0]
            }))}
            value={tool ? step.tool : undefined}
            onChange={chooseTool}
            placeholder={t("flow_editor_tool_pick")}
            hasSearch={tools.length > 8}
            isRequired
            status={problemStatus(
              problems.tool ??
                (availability === "unknown_tool" && step.tool
                  ? t("flow_function_unknown_tool_short")
                  : undefined)
            )}
          />
        ) : (
          <TextInput
            label={t("flow_editor_tool")}
            description={
              availability === "unknown"
                ? t("flow_editor_tool_hint")
                : t("flow_editor_tool_no_provider")
            }
            value={step.tool}
            onChange={(name) => draft.update({ tool: name.trim() })}
            isRequired
            status={problemStatus(problems.tool)}
          />
        )}
      </div>
      <div className="flex flex-col gap-1.5">
        <JsonTextField
          label={t("flow_param_arguments")}
          description={t("flow_editor_arguments_hint")}
          json={draft.draft.json.arguments}
          onChange={(text) => draft.setJson("arguments", text)}
          problem={problems.arguments}
        />
        {argumentNames.length > 0 && (
          <Text type="supporting" size="xsm" as="p" display="block" className="m-0 leading-snug">
            {t("flow_editor_tool_arguments", { names: argumentNames.join(", ") })}
          </Text>
        )}
        <TemplateHint definition={definition} stepKey={step.key} />
      </div>
      <FilesFromField
        definition={definition}
        value={step.files_from ?? []}
        onChange={(files_from) => draft.update({ files_from })}
        problem={problems.files_from}
      />
    </>
  );
}
