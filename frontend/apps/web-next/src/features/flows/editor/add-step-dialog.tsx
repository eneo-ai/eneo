"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { TextInput } from "@/components/astryx/text-input";
import { getFlow, toolOptionsQueryOptions, updateFlowEditor } from "./editor-api";
import { problemStatus } from "./editor-fields";
import { describeSaveError, isStaleRevision } from "./field-problems";
import { httpUrlProblem } from "./step-configs";
import {
  kindBlock,
  newStepUpdate,
  STEP_KINDS,
  stepNameTaken,
  uniqueStepName,
  type DocumentFormat,
  type KindBlock,
  type StepKind
} from "./step-kinds";
import { stepLabel } from "./step-labels";
import type { FlowPublic, ToolOption } from "./step-types";

type Field = "kind" | "name" | "url" | "tool";
type Problems = Partial<Record<Field, string>>;

function blockText(block: KindBlock, t: ReturnType<typeof useTranslations>): string {
  return t(`flow_step_editor_kind_block_${block}`);
}

function toolKey(tool: Pick<ToolOption, "mcp_server_id" | "tool_id">): string {
  return `${tool.mcp_server_id}:${tool.tool_id}`;
}

function ToolChoice({
  flowId,
  value,
  onChange,
  problem,
  inputRef
}: {
  flowId: string;
  value: string | null;
  onChange: (tool: ToolOption) => void;
  problem?: string;
  inputRef: React.RefObject<HTMLDivElement | null>;
}) {
  const t = useTranslations();
  const options = useQuery(toolOptionsQueryOptions(flowId));
  const items = options.data?.items ?? [];
  const servers = [...new Set(items.map((item) => item.mcp_server_id))];
  return (
    <div ref={inputRef}>
      <Selector
        label={t("flow_step_editor_tool")}
        description={
          options.isError
            ? t("flow_step_editor_tools_failed")
            : options.isSuccess && items.length === 0
              ? t("flow_step_editor_tools_none")
              : t("flow_step_editor_tool_description")
        }
        options={servers.map((serverId) => {
          const serverTools = items.filter((item) => item.mcp_server_id === serverId);
          return {
            type: "section" as const,
            title: serverTools[0]?.mcp_server_name ?? serverId,
            options: serverTools.map((item) => ({
              value: toolKey(item),
              label: item.tool_name,
              description: item.tool_description ?? undefined
            }))
          };
        })}
        value={value ?? undefined}
        placeholder={t("flow_step_editor_tool_placeholder")}
        isLoading={options.isPending}
        hasSearch={items.length > 8}
        isRequired
        onChange={(key) => {
          const item = items.find((candidate) => toolKey(candidate) === key);
          if (item) onChange(item);
        }}
        status={problemStatus(problem)}
        width="100%"
      />
    </div>
  );
}

/** The form of the dialog; it mounts each time the dialog opens, so it starts empty. */
function AddStepForm({
  flow: propFlow,
  position: requestedPosition,
  formId,
  onClose,
  onSaved,
  onPendingChange
}: {
  flow: FlowPublic;
  position: number;
  formId: string;
  onClose: () => void;
  onSaved: (flow: FlowPublic) => void;
  onPendingChange: (pending: boolean) => void;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const [reloaded, setReloaded] = useState<FlowPublic | null>(null);
  const flow = reloaded && reloaded.draft_revision >= propFlow.draft_revision ? reloaded : propFlow;
  const position = Math.min(Math.max(1, Math.round(requestedPosition)), flow.steps.length + 1);
  const [format, setFormat] = useState<DocumentFormat>("docx");
  const firstAvailable =
    STEP_KINDS.find((kind) => kindBlock(flow, position, kind) === null) ?? "ai";
  const [kind, setKind] = useState<StepKind>(firstAvailable);
  const kindDefault = (value: StepKind) =>
    uniqueStepName(flow, t(`flow_step_editor_kind_${value}_name`));
  const [name, setName] = useState(() => kindDefault(firstAvailable));
  const [url, setUrl] = useState("");
  const [tool, setTool] = useState<ToolOption | null>(null);
  const [problems, setProblems] = useState<Problems>({});
  const [formProblem, setFormProblem] = useState<{ message: string; stale: boolean } | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const urlRef = useRef<HTMLInputElement>(null);
  const toolRef = useRef<HTMLDivElement>(null);
  const kindRef = useRef<HTMLDivElement>(null);
  const summaryRef = useRef<HTMLDivElement>(null);
  const needsUrl = kind === "fetch_http" || kind === "send_http";

  const add = useMutation({
    mutationFn: () =>
      updateFlowEditor(
        flow.id,
        newStepUpdate(flow, position, kind, {
          name,
          format,
          url,
          tool: tool
            ? { mcp_server_id: tool.mcp_server_id, tool_id: tool.tool_id, arguments: {} }
            : null
        })
      ),
    onMutate: () => onPendingChange(true),
    onSettled: () => onPendingChange(false),
    onSuccess: (updated) => {
      announce(t("flow_step_editor_added", { name: name.trim() }));
      onSaved(updated);
      onClose();
    },
    onError: (error) => {
      if (isStaleRevision(error)) {
        flushSync(() => setFormProblem({ message: t("flow_step_editor_add_stale"), stale: true }));
        summaryRef.current?.focus();
        return;
      }
      const problem = describeSaveError(
        error,
        {
          stepId: "",
          stepOrder: position,
          config: {
            input_source:
              kind === "fetch_http" ? "http_get" : kind === "tool" ? "tool" : "flow_input",
            output_mode: kind === "send_http" ? "http_post" : "pass_through"
          }
        },
        t
      );
      const field: Field | null =
        problem.anchor === "user_description"
          ? "name"
          : problem.anchor === "input_config.http" || problem.anchor === "output_config.http"
            ? "url"
            : problem.anchor === "input_config.tool"
              ? "tool"
              : null;
      if (field && problem.otherStepOrder === null) {
        flushSync(() => {
          setProblems({ [field]: problem.message });
          setFormProblem(null);
        });
        focusField(field);
      } else {
        const message =
          problem.otherStepOrder !== null
            ? t("flow_step_editor_other_step_problem", {
                step: stepLabel(
                  problem.otherStepOrder,
                  flow.steps.find((step) => step.step_order === problem.otherStepOrder)
                    ?.user_description,
                  t
                ),
                message: problem.message
              })
            : problem.message;
        flushSync(() => setFormProblem({ message, stale: false }));
        summaryRef.current?.focus();
      }
    }
  });

  const reload = useMutation({
    mutationFn: () => getFlow(flow.id),
    onSuccess: (fresh) => {
      setReloaded(fresh);
      setFormProblem(null);
      announce(t("flow_step_editor_reloaded"));
    }
  });

  function focusField(field: Field) {
    if (field === "name") nameRef.current?.focus();
    else if (field === "url") urlRef.current?.focus();
    else if (field === "tool")
      toolRef.current?.querySelector<HTMLElement>("button, [role=combobox]")?.focus();
    else kindRef.current?.querySelector<HTMLElement>("input")?.focus();
  }

  function chooseKind(next: StepKind) {
    const previousDefault = kindDefault(kind);
    setKind(next);
    if (!name.trim() || name === previousDefault) setName(kindDefault(next));
    setProblems((current) => ({ ...current, kind: undefined }));
  }

  function check(): Problems {
    const found: Problems = {};
    const block = kindBlock(flow, position, kind, format);
    if (block) found.kind = blockText(block, t);
    const trimmed = name.trim();
    if (!trimmed) found.name = t("flow_step_editor_name_required");
    else if (trimmed.length > 200) found.name = t("flow_step_editor_name_too_long");
    else if (stepNameTaken(flow, trimmed)) found.name = t("flow_step_editor_name_taken");
    if (needsUrl) {
      const urlProblem = httpUrlProblem(url);
      if (urlProblem === "missing") found.url = t("flow_step_editor_http_url_missing");
      else if (urlProblem === "invalid") found.url = t("flow_step_editor_http_url_invalid");
    }
    if (kind === "tool" && !tool) found.tool = t("flow_step_editor_tool_required");
    return found;
  }

  function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (add.isPending) return;
    const found = check();
    const first = (["kind", "name", "url", "tool"] as const).find((field) => found[field]);
    if (first) {
      flushSync(() => setProblems(found));
      focusField(first);
      return;
    }
    setProblems({});
    setFormProblem(null);
    add.mutate();
  }

  return (
    <form id={formId} noValidate onSubmit={submit} className="flex flex-col gap-5">
      <Text type="supporting" size="sm" as="p" display="block" className="m-0">
        {t("flow_step_editor_add_position", { position })}
      </Text>
      <div
        ref={summaryRef}
        tabIndex={-1}
        className="focus-visible:outline-ring outline-none focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        {formProblem && (
          <Banner
            status="error"
            title={t("flow_step_editor_add_refused")}
            description={formProblem.message}
            collapsible={false}
            endContent={
              formProblem.stale ? (
                <Button
                  label={t("flow_step_editor_reload")}
                  size="sm"
                  isLoading={reload.isPending}
                  isInterruptible
                  onClick={() => {
                    if (!reload.isPending) reload.mutate();
                  }}
                />
              ) : undefined
            }
          />
        )}
      </div>
      <div ref={kindRef}>
        <RadioList
          label={t("flow_step_editor_kind")}
          description={t("flow_step_editor_kind_description")}
          value={kind}
          onChange={(value) => chooseKind(value as StepKind)}
          status={problemStatus(problems.kind)}
          isRequired
        >
          {STEP_KINDS.map((value) => {
            const block = kindBlock(flow, position, value, format);
            return (
              <RadioListItem
                key={value}
                value={value}
                label={t(`flow_step_editor_kind_${value}`)}
                description={
                  block
                    ? `${t(`flow_step_editor_kind_${value}_description`)} ${blockText(block, t)}`
                    : t(`flow_step_editor_kind_${value}_description`)
                }
                isDisabled={block !== null && value !== kind}
              />
            );
          })}
        </RadioList>
      </div>
      {kind === "document" && (
        <RadioList
          label={t("flow_step_editor_document_format")}
          value={format}
          onChange={(value) => setFormat(value === "pdf" ? "pdf" : "docx")}
          orientation="horizontal"
        >
          <RadioListItem value="docx" label={t("flow_output_type_docx")} />
          <RadioListItem value="pdf" label={t("flow_output_type_pdf")} />
        </RadioList>
      )}
      <TextInput
        ref={nameRef}
        label={t("flow_step_name")}
        description={t("flow_step_editor_name_description")}
        value={name}
        onChange={(value) => {
          setName(value);
          if (value.trim()) setProblems((current) => ({ ...current, name: undefined }));
        }}
        isRequired
        autoComplete="off"
        status={problemStatus(problems.name)}
      />
      {needsUrl && (
        <TextInput
          ref={urlRef}
          label={
            kind === "fetch_http"
              ? t("flow_step_editor_http_url_get")
              : t("flow_step_editor_http_url_post")
          }
          description={t("flow_step_editor_http_url_description")}
          value={url}
          onChange={(value) => {
            setUrl(value);
            setProblems((current) => ({ ...current, url: undefined }));
          }}
          isRequired
          autoComplete="off"
          status={problemStatus(problems.url)}
        />
      )}
      {kind === "tool" && (
        <ToolChoice
          flowId={flow.id}
          value={tool ? toolKey(tool) : null}
          onChange={(next) => {
            setTool(next);
            setProblems((current) => ({ ...current, tool: undefined }));
          }}
          problem={problems.tool}
          inputRef={toolRef}
        />
      )}
      <Text type="supporting" size="sm" as="p" display="block" className="m-0">
        {t("flow_step_editor_add_then_configure")}
      </Text>
    </form>
  );
}

/**
 * Adds a step at `position` (1-based): the author picks what the step does
 * and names it, and the step starts with a configuration that is valid
 * where it lands. Saved as one editor change (`new_steps` + `step_order`).
 */
export function AddStepDialog({
  flow,
  position,
  open,
  onOpenChange,
  onSaved
}: {
  flow: FlowPublic;
  position: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: (flow: FlowPublic) => void;
}): React.JSX.Element {
  const t = useTranslations();
  const formId = useId();
  const [pending, setPending] = useState(false);

  function requestOpenChange(next: boolean) {
    if (!next && pending) return;
    onOpenChange(next);
  }

  return (
    <Dialog
      isOpen={open}
      onOpenChange={requestOpenChange}
      purpose="form"
      width={560}
      maxHeight="85dvh"
    >
      <Layout
        height="auto"
        header={
          <DialogHeader title={t("flow_step_editor_add_title")} onOpenChange={requestOpenChange} />
        }
        content={
          open ? (
            <LayoutContent>
              <AddStepForm
                flow={flow}
                position={position}
                formId={formId}
                onClose={() => onOpenChange(false)}
                onSaved={onSaved}
                onPendingChange={setPending}
              />
            </LayoutContent>
          ) : null
        }
        footer={
          open ? (
            <LayoutFooter>
              <div className="flex flex-wrap justify-end gap-2">
                <Button
                  label={t("cancel")}
                  isDisabled={pending}
                  onClick={() => requestOpenChange(false)}
                />
                <Button
                  type="submit"
                  form={formId}
                  variant="primary"
                  label={t("flow_step_editor_add_submit")}
                  isLoading={pending}
                  isInterruptible
                />
              </div>
            </LayoutFooter>
          ) : null
        }
      />
    </Dialog>
  );
}
