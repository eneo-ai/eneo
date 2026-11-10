import { Button } from "@astryxdesign/core/Button";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { Text } from "@astryxdesign/core/Text";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { useId, useRef, useState } from "react";
import { useSpace } from "@/features/spaces/use-space";
import { cn } from "@/lib/utils";
import { useFlowReadLabel } from "../flow-read-layout";
import { knownClassifications, levelName } from "./classification-names";
import {
  securityClassificationsQueryOptions,
  templateInspectionQueryOptions,
  toolOptionsQueryOptions
} from "./editor-api";
import { answerShape, previewParts } from "./request-preview";
import {
  hasHttpConfig,
  readCitationsOn,
  readHttpConfig,
  readInputBindings,
  readLongMaterial,
  readRuntimeInput,
  readTemplateFill,
  readToolConfig,
  reviewChoiceOf,
  sourceRefKey
} from "./step-configs";
import { sourceRefName } from "./step-input-section";
import {
  httpAuthSummary,
  httpBodyModeLabel,
  inputSourceLabel,
  inputTypeLabel,
  meaningLabel,
  outputModeLabel,
  outputTypeLabel,
  reviewChoiceLabel
} from "./step-labels";
import { stepUsesModel } from "./step-rules";
import type { AssistantConfig, FlowPublic, StepConfig } from "./step-types";

// ponytail: a length guess, not a measured overflow; a text under it is never clamped, so nothing hides.
const LONG_TEXT = 480;
const LONG_LINES = 6;

/**
 * A text as written, at a reading width. A long one (an instruction of a
 * few thousand characters) shows its first lines with "Visa hela", so the
 * rest of the step stays in view.
 */
function Paragraph({ children }: { children: string }) {
  const t = useTranslations();
  const id = useId();
  const [open, setOpen] = useState(false);
  const long = children.length > LONG_TEXT || children.split("\n").length > LONG_LINES;
  return (
    <div className="flex max-w-prose flex-col items-start gap-1">
      <Text
        as="p"
        display="block"
        id={id}
        className={cn(
          "m-0 [overflow-wrap:anywhere] whitespace-pre-wrap",
          long && !open && "line-clamp-6"
        )}
      >
        {children}
      </Text>
      {long ? (
        <Button
          size="sm"
          variant="ghost"
          label={open ? t("flows_change_card_show_less") : t("flows_change_card_show_all")}
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setOpen((value) => !value)}
        />
      ) : null}
    </div>
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

/** The step's settings as text, for a reader who cannot change them. */
export function StepReadOnly({
  flow,
  step,
  stepOrder,
  assistant
}: {
  flow: FlowPublic;
  step: StepConfig;
  stepOrder: number;
  assistant: AssistantConfig | null;
}) {
  const t = useTranslations();
  const { space } = useSpace();
  const rootRef = useRef<HTMLDivElement>(null);
  const label = useFlowReadLabel(rootRef);
  const listing = useQuery(securityClassificationsQueryOptions());
  const classifications = knownClassifications(listing.data?.items, space);
  const runtime = readRuntimeInput(step.input_config);
  const bindings = readInputBindings(step.input_bindings);
  const tool = readToolConfig(step.input_config);
  const template = readTemplateFill(step.output_config);
  // The Word fields by the titles the editor shows; their tags while the template is read.
  // Only an editor may inspect (a published flow keeps `can_edit`); a reader sees the tags.
  const inspection = useQuery({
    ...templateInspectionQueryOptions(flow.id, template.templateAssetId ?? ""),
    enabled:
      flow.permissions.can_edit &&
      step.output_mode === "template_fill" &&
      template.templateAssetId !== null
  });
  const fieldTitle = (name: string) =>
    inspection.data?.placeholders.find((item) => item.name === name)?.label?.trim() || name;
  const answer = answerShape(step);
  // Results or a text chosen under "Välj själv vad steget läser" replace the source.
  const chosenMaterial =
    bindings.status === "valid" &&
    (bindings.sourceRefs.length > 0 || bindings.question.trim() !== "");
  const review = reviewChoiceOf(step.review_policy);
  const httpIn =
    step.input_source === "http_get" && hasHttpConfig(step.input_config)
      ? readHttpConfig(step.input_config, "input")
      : null;
  const httpOut =
    step.output_mode === "http_post" && hasHttpConfig(step.output_config)
      ? readHttpConfig(step.output_config, "output")
      : null;
  const model = assistant?.completion_model_id
    ? space.completion_models.find((candidate) => candidate.id === assistant.completion_model_id)
    : null;
  const knowledge = assistant
    ? [...assistant.groups, ...assistant.websites, ...assistant.integration_knowledge_list].map(
        (item) =>
          "name" in item && item.name ? item.name : "url" in item ? String(item.url) : item.id
      )
    : [];
  // What fills a template field, as a reference pill in the editor names it.
  const templateSource = (binding: string | undefined) =>
    binding === undefined
      ? t("flow_step_editor_template_field_none")
      : binding === ""
        ? t("flow_step_editor_template_field_left_empty")
        : previewParts(binding, stepOrder, flow)
            .map((part) =>
              part.kind === "text" ? part.text : meaningLabel(part.meaning, part.token, flow, t)
            )
            .join("")
            .trim();
  const yes = t("flow_step_editor_yes");
  const no = t("flow_step_editor_no");

  return (
    <div ref={rootRef} className="flex flex-col gap-6">
      <MetadataList title={t("flow_step_editor_input_title")} label={label}>
        <MetadataListItem label={t("flow_step_editor_input_source")}>
          {chosenMaterial
            ? t("flow_step_editor_source_chosen")
            : inputSourceLabel(step.input_source, t)}
        </MetadataListItem>
        <MetadataListItem label={t("flow_step_input_type")}>
          {inputTypeLabel(step.input_type, t)}
        </MetadataListItem>
        {step.input_source === "flow_input" && (
          <MetadataListItem label={t("flow_step_editor_uploads_enabled")}>
            {runtime.enabled
              ? runtime.required
                ? t("flow_step_editor_uploads_required_summary")
                : yes
              : no}
          </MetadataListItem>
        )}
        {runtime.enabled && (
          <>
            <MetadataListItem label={t("flow_runtime_input_format_label")}>
              {t(`flow_runtime_input_format_${runtime.inputFormat}`)}
            </MetadataListItem>
            <MetadataListItem label={t("flow_runtime_input_mimetypes_label")}>
              {runtime.acceptedMimetypes.length
                ? runtime.acceptedMimetypes.join(", ")
                : t("flow_runtime_input_mimetypes_default")}
            </MetadataListItem>
          </>
        )}
        {httpIn && (
          <>
            <MetadataListItem label={t("flow_step_editor_http_url_get")}>
              <span className="[overflow-wrap:anywhere]">{httpIn.url}</span>
            </MetadataListItem>
            <MetadataListItem label={t("flow_step_editor_http_auth")}>
              {httpAuthSummary(httpIn.auth, t)}
            </MetadataListItem>
          </>
        )}
        {step.input_source === "tool" && (
          <MetadataListItem label={t("flow_step_editor_tool")}>
            {tool ? (
              <ToolName flowId={flow.id} serverId={tool.mcp_server_id} toolId={tool.tool_id} />
            ) : (
              t("flow_step_editor_tool_placeholder")
            )}
          </MetadataListItem>
        )}
        {readLongMaterial(step.input_config) && (
          <MetadataListItem label={t("flow_editor_tools_long_material")}>
            {t("flow_editor_tools_on")}
          </MetadataListItem>
        )}
        {bindings.status === "valid" && bindings.sourceRefs.length > 0 && (
          <MetadataListItem label={t("flow_step_editor_underlag_results")}>
            {/* One per line: a name can hold a comma ("Steg 2: Sammanfatta, fältet beslut"). */}
            <ul className="m-0 flex list-none flex-col gap-1 p-0">
              {bindings.sourceRefs.map((ref) => (
                <li key={sourceRefKey(ref)}>{sourceRefName(ref, flow, t)}</li>
              ))}
            </ul>
          </MetadataListItem>
        )}
        {bindings.status === "valid" && bindings.question.trim() && (
          <MetadataListItem label={t("flow_step_editor_underlag_text")}>
            <Paragraph>{bindings.question}</Paragraph>
          </MetadataListItem>
        )}
      </MetadataList>

      {stepUsesModel(step) && assistant && (
        <MetadataList title={t("flow_step_editor_ai_title")} label={label}>
          <MetadataListItem label={t("flow_step_editor_instruction")}>
            <Paragraph>
              {assistant.prompt.trim() || t("flow_step_editor_instruction_none")}
            </Paragraph>
          </MetadataListItem>
          <MetadataListItem label={t("flow_step_editor_model")}>
            {model ? model.nickname?.trim() || model.name : t("flow_step_editor_model_unknown")}
          </MetadataListItem>
          <MetadataListItem label={t("knowledge")}>
            {knowledge.length > 0 ? knowledge.join(", ") : t("flow_step_editor_knowledge_none")}
          </MetadataListItem>
          {assistant.attachments.length > 0 && (
            <MetadataListItem label={t("flow_step_editor_attachments")}>
              {assistant.attachments.map((file) => file.name).join(", ")}
            </MetadataListItem>
          )}
        </MetadataList>
      )}

      <MetadataList title={t("flow_step_editor_output_title")} label={label}>
        <MetadataListItem label={t("flow_step_output_mode")}>
          {outputModeLabel(step.output_mode, t)}
        </MetadataListItem>
        <MetadataListItem label={t("flow_step_output_type")}>
          {outputTypeLabel(step.output_type, t)}
        </MetadataListItem>
        {httpOut && (
          <>
            <MetadataListItem label={t("flow_step_editor_http_url_post")}>
              <span className="[overflow-wrap:anywhere]">{httpOut.url}</span>
            </MetadataListItem>
            <MetadataListItem label={t("flow_step_editor_http_auth")}>
              {httpAuthSummary(httpOut.auth, t)}
            </MetadataListItem>
            <MetadataListItem label={t("flow_step_editor_http_body")}>
              {httpBodyModeLabel(httpOut.body.mode, t)}
            </MetadataListItem>
          </>
        )}
        {step.output_mode === "template_fill" && (
          <MetadataListItem label={t("flow_step_editor_template")}>
            {template.templateName ?? t("flow_step_editor_template_none")}
          </MetadataListItem>
        )}
        {step.output_mode === "template_fill" && template.placeholders.length > 0 && (
          <MetadataListItem label={t("flow_step_editor_template_fields")}>
            <ul className="m-0 flex list-none flex-col gap-1 p-0">
              {template.placeholders.map((name) => (
                <li key={name}>
                  {t("flow_step_editor_template_field_reads", {
                    field: fieldTitle(name),
                    source: templateSource(template.bindings[name])
                  })}
                </li>
              ))}
            </ul>
          </MetadataListItem>
        )}
        {answer.kind === "fields" && answer.fields.length > 0 && (
          <MetadataListItem label={t("flow_step_editor_answer_fields")}>
            <ul className="m-0 flex list-none flex-col gap-1 p-0">
              {answer.fields.map((field) => (
                <li key={field.name} className="[overflow-wrap:anywhere]">
                  <code className="font-mono text-xs">{field.name}</code>
                  {field.description ? ` · ${field.description}` : ""}
                </li>
              ))}
            </ul>
          </MetadataListItem>
        )}
        {readCitationsOn(step.output_config) && (
          <MetadataListItem label={t("flow_step_citation_mode")}>
            {t("flow_step_citation_mode_inline_inref_sidecar")}
          </MetadataListItem>
        )}
      </MetadataList>

      <MetadataList title={t("flow_step_editor_control_title")} label={label}>
        <MetadataListItem label={t("flow_step_review_policy")}>
          {reviewChoiceLabel(review, t)}
        </MetadataListItem>
        <MetadataListItem label={t("flow_step_security_classification")}>
          {step.output_classification_override === null
            ? t("flow_step_security_inherit")
            : levelName(step.output_classification_override, classifications, t)}
        </MetadataListItem>
        {step.timeout_seconds !== null && (
          <MetadataListItem label={t("flow_step_editor_timeout")}>
            {t("flow_step_editor_seconds", { count: step.timeout_seconds })}
          </MetadataListItem>
        )}
      </MetadataList>
    </div>
  );
}
