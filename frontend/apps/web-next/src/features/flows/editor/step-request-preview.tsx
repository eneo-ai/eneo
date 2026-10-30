"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";
import { useQuery } from "@tanstack/react-query";
import { ScanEye } from "lucide-react";
import { useTranslations } from "use-intl";
import { useState } from "react";
import { modelDisplayName } from "@/features/spaces/space-models";
import { useSpace } from "@/features/spaces/use-space";
import { toolOptionsQueryOptions } from "./editor-api";
import { tokenColor } from "./reference-text-area";
import { answerShape, modelParameters, previewParts, type PreviewPart } from "./request-preview";
import {
  argumentText,
  hasHttpConfig,
  readHttpConfig,
  readInputBindings,
  readLongMaterial,
  readTextProcessingMode,
  readToolConfig,
  sourceRefStepOrder
} from "./step-configs";
import { inputSourceLabel, meaningLabel, stepLabel } from "./step-labels";
import { stepUsesModel } from "./step-rules";
import type { AssistantConfig, FlowPublic, StepConfig } from "./step-types";

/** A text as the step sends it, every reference a chip that says what it reads. */
function Template({ parts, flow }: { parts: PreviewPart[]; flow: FlowPublic }) {
  const t = useTranslations();
  return (
    <p className="bg-ax-sunken rounded-ax-element text-ax-text m-0 px-3 py-2 text-sm leading-relaxed break-words whitespace-pre-wrap">
      {parts.map((part, index) =>
        part.kind === "text" ? (
          <span key={index}>{part.text}</span>
        ) : (
          <Token
            key={index}
            size="sm"
            color={tokenColor(part.meaning)}
            label={meaningLabel(part.meaning, part.token, flow, t)}
            description={`{{${part.token}}}`}
            className="mx-0.5 align-baseline"
          />
        )
      )}
    </p>
  );
}

function ToolName({
  flowId,
  serverId,
  toolId
}: {
  flowId: string;
  serverId: string;
  toolId: string;
}) {
  const t = useTranslations();
  const options = useQuery(toolOptionsQueryOptions(flowId));
  const item = options.data?.items.find(
    (candidate) => candidate.mcp_server_id === serverId && candidate.tool_id === toolId
  );
  return (
    <>
      {item
        ? t("flow_step_editor_tool_named", { tool: item.tool_name, server: item.mcp_server_name })
        : t("flow_step_editor_tool_unavailable")}
    </>
  );
}

/**
 * What the step would send as it stands, unsaved edits included: its
 * instruction and underlag with every reference named for what it reads, the
 * model and its settings, the knowledge and files it reads, a tool call's
 * arguments or an HTTP call's address, and what the answer must hold. Stored
 * credentials are never shown, only that one is stored.
 */
function RequestPreview({
  flow,
  stepOrder,
  draft,
  assistant
}: {
  flow: FlowPublic;
  stepOrder: number;
  draft: StepConfig;
  assistant: AssistantConfig;
}) {
  const t = useTranslations();
  const { space } = useSpace();
  const usesModel = stepUsesModel(draft);
  const bindings = readInputBindings(draft.input_bindings);
  const tool = draft.input_source === "tool" ? readToolConfig(draft.input_config) : null;
  const http =
    draft.input_source === "http_get" && hasHttpConfig(draft.input_config)
      ? { method: "GET", config: readHttpConfig(draft.input_config, "input") }
      : draft.output_mode === "http_post" && hasHttpConfig(draft.output_config)
        ? { method: "POST", config: readHttpConfig(draft.output_config, "output") }
        : null;
  const model = space.completion_models.find((item) => item.id === assistant.completion_model_id);
  const parameters = modelParameters(assistant.completion_model_kwargs);
  const knowledge = [
    ...assistant.groups,
    ...assistant.websites,
    ...assistant.integration_knowledge_list
  ].map((item) =>
    "name" in item && item.name ? item.name : "url" in item ? String(item.url) : item.id
  );
  const answer = answerShape(draft);
  const readingMode = readTextProcessingMode(draft.input_config);

  return (
    <div className="flex flex-col gap-5">
      {usesModel ? (
        <section className="flex flex-col gap-2">
          <Text type="label" as="h3" display="block" className="m-0">
            {t("flow_step_editor_instruction")}
          </Text>
          {assistant.prompt.trim() ? (
            <Template
              parts={previewParts(assistant.prompt, stepOrder, flow, {
                sectionIndex: readingMode === "process_each_section"
              })}
              flow={flow}
            />
          ) : (
            <Text type="supporting" size="sm" as="p" display="block" className="m-0">
              {t("flow_step_editor_instruction_none")}
            </Text>
          )}
        </section>
      ) : null}

      <section className="flex flex-col gap-2">
        <Text type="label" as="h3" display="block" className="m-0">
          {t("flow_editor_tools_preview_material")}
        </Text>
        <Text type="body" size="sm" as="p" display="block" className="m-0">
          {bindings.status === "valid" &&
          (bindings.question.trim() || bindings.sourceRefs.length > 0)
            ? t("flow_editor_tools_preview_material_underlag")
            : t("flow_editor_tools_preview_material_source", {
                source: inputSourceLabel(draft.input_source, t)
              })}
          {readingMode ? ` ${t(`flow_editor_tools_preview_reading_${readingMode}`)}` : ""}
          {readLongMaterial(draft.input_config)
            ? ` ${t("flow_editor_tools_preview_long_material")}`
            : ""}
        </Text>
        {bindings.status === "valid" && bindings.sourceRefs.length > 0 ? (
          <ul className="text-ax-text m-0 list-disc pl-5 text-sm">
            {bindings.sourceRefs.map((ref) => {
              const order = sourceRefStepOrder(ref);
              const source =
                order === null
                  ? ref.stepRef
                  : stepLabel(
                      order,
                      flow.steps.find((item) => item.step_order === order)?.user_description,
                      t
                    );
              return (
                <li key={`${ref.stepRef}:${ref.output}:${ref.fieldPath ?? ""}`}>
                  {ref.fieldPath
                    ? t("flow_step_editor_underlag_field", { step: source, field: ref.fieldPath })
                    : source}
                </li>
              );
            })}
          </ul>
        ) : null}
        {bindings.status === "valid" && bindings.question.trim() ? (
          <Template parts={previewParts(bindings.question, stepOrder, flow)} flow={flow} />
        ) : null}
        {tool ? (
          <MetadataList label={{ position: "start", width: "8rem" }}>
            <MetadataListItem label={t("flow_step_editor_tool")}>
              <ToolName flowId={flow.id} serverId={tool.mcp_server_id} toolId={tool.tool_id} />
            </MetadataListItem>
            {Object.entries(tool.arguments).map(([name, value]) => (
              <MetadataListItem key={name} label={name}>
                {typeof value === "string" && value.includes("{{") ? (
                  <Template parts={previewParts(value, stepOrder, flow)} flow={flow} />
                ) : (
                  <code className="font-mono text-xs break-all">{argumentText(value)}</code>
                )}
              </MetadataListItem>
            ))}
          </MetadataList>
        ) : null}
        {http ? (
          <MetadataList label={{ position: "start", width: "8rem" }}>
            <MetadataListItem label={t("flow_editor_tools_preview_http_address")}>
              <span className="flex flex-wrap items-baseline gap-1">
                <code className="font-mono text-xs">{http.method}</code>
                <Template parts={previewParts(http.config.url, stepOrder, flow)} flow={flow} />
              </span>
            </MetadataListItem>
            <MetadataListItem label={t("flow_step_editor_http_auth")}>
              {http.config.auth.mode === "none"
                ? t("flow_editor_tools_preview_http_no_auth")
                : t("flow_step_editor_secret_stored")}
            </MetadataListItem>
            {http.config.custom_headers.length > 0 ? (
              <MetadataListItem label={t("flow_editor_tools_preview_http_headers")}>
                {http.config.custom_headers
                  .map((header) => header.name)
                  .filter(Boolean)
                  .join(", ")}
              </MetadataListItem>
            ) : null}
            {http.config.body.template ? (
              <MetadataListItem label={t("flow_editor_tools_preview_http_body")}>
                <Template
                  parts={previewParts(http.config.body.template, stepOrder, flow)}
                  flow={flow}
                />
              </MetadataListItem>
            ) : null}
          </MetadataList>
        ) : null}
      </section>

      {usesModel ? (
        <MetadataList
          title={t("flow_editor_tools_preview_model_title")}
          label={{ position: "start", width: "8rem" }}
        >
          <MetadataListItem label={t("completion_model")}>
            {model ? modelDisplayName(model) : t("flow_step_editor_model_unknown")}
          </MetadataListItem>
          <MetadataListItem label={t("flow_editor_tools_preview_parameters")}>
            {parameters.length === 0 ? (
              t("flow_editor_tools_preview_parameters_default")
            ) : (
              <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
                {parameters.map((parameter) => (
                  <li key={parameter.name}>
                    <code className="font-mono text-xs">
                      {parameter.name}: {parameter.value}
                    </code>
                  </li>
                ))}
              </ul>
            )}
          </MetadataListItem>
          <MetadataListItem label={t("knowledge")}>
            {knowledge.length > 0 ? knowledge.join(", ") : t("flow_step_editor_knowledge_none")}
          </MetadataListItem>
          {assistant.attachments.length > 0 ? (
            <MetadataListItem label={t("flow_step_editor_attachments")}>
              {assistant.attachments.map((file) => file.name).join(", ")}
            </MetadataListItem>
          ) : null}
        </MetadataList>
      ) : null}

      <section className="flex flex-col gap-2">
        <Text type="label" as="h3" display="block" className="m-0">
          {t("flow_editor_tools_preview_answer")}
        </Text>
        {answer.kind === "fields" ? (
          answer.fields.length > 0 ? (
            <ul className="text-ax-text m-0 list-disc pl-5 text-sm">
              {answer.fields.map((field) => (
                <li key={field.name}>
                  <code className="font-mono text-xs">{field.name}</code>
                  {field.description ? ` · ${field.description}` : ""}
                </li>
              ))}
            </ul>
          ) : (
            <Text type="body" size="sm" as="p" display="block" className="m-0">
              {t("flow_editor_tools_preview_answer_json")}
            </Text>
          )
        ) : (
          <Text type="body" size="sm" as="p" display="block" className="m-0">
            {answer.kind === "document"
              ? t("flow_editor_tools_preview_answer_document", {
                  format: answer.format.toUpperCase()
                })
              : t("flow_editor_tools_preview_answer_text")}
          </Text>
        )}
      </section>
    </div>
  );
}

/** "Visa anropet": opens the step's request preview in a dialog. */
export function StepRequestPreviewButton(props: {
  flow: FlowPublic;
  stepOrder: number;
  draft: StepConfig;
  assistant: AssistantConfig;
}) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  return (
    <>
      <div>
        <Button
          label={t("flow_editor_tools_preview_button")}
          icon={<ScanEye className="size-4" aria-hidden="true" />}
          size="sm"
          onClick={() => setOpen(true)}
        />
      </div>
      <Dialog isOpen={open} onOpenChange={setOpen} width={680}>
        <Layout
          height="auto"
          header={
            <DialogHeader
              title={t("flow_editor_tools_preview_title")}
              subtitle={t("flow_editor_tools_preview_description")}
              onOpenChange={setOpen}
            />
          }
          content={
            open ? (
              <LayoutContent>
                <RequestPreview {...props} />
              </LayoutContent>
            ) : null
          }
          footer={
            open ? (
              <LayoutFooter>
                <div className="flex justify-end">
                  <Button label={t("close")} onClick={() => setOpen(false)} />
                </div>
              </LayoutFooter>
            ) : null
          }
        />
      </Dialog>
    </>
  );
}
