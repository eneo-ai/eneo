"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { useTranslations } from "use-intl";
import { useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { TextInput } from "@astryxdesign/core/TextInput";
import { toast } from "@/lib/toast";
import { saveBlob } from "@/features/files/signed-file-url";
import type { FlowPublic } from "./flows-api";
import {
  defaultPackageId,
  exportFlowPackage,
  normalizePackageId,
  packageRefusalMessage,
  PACKAGE_ID_MAX_LENGTH,
  type PackageExport
} from "./flow-packages";

/**
 * "Exportera": saves the flow as a `.eneopkg` file another Eneo installation
 * can import. The package carries the steps, their instructions, the run form
 * and what models and knowledge the steps need, never run history or
 * credentials; Word templates only when chosen. MCP connections stay behind:
 * when the flow has them, the file is kept until the person says they
 * understand. Controlled by the caller, which renders the trigger.
 */
export function FlowPackageExportDialog({
  flow,
  open,
  onOpenChange
}: {
  flow: FlowPublic;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const formId = useId();
  const errorRef = useRef<HTMLDivElement>(null);
  const [packageId, setPackageId] = useState(() => defaultPackageId(flow.name));
  const [idEdited, setIdEdited] = useState(false);
  const [version, setVersion] = useState("1.0.0");
  const [name, setName] = useState(flow.name);
  const [description, setDescription] = useState(flow.description ?? "");
  const [includeTemplates, setIncludeTemplates] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [showProblems, setShowProblems] = useState(false);
  const [pending, setPending] = useState<PackageExport | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [ackMissing, setAckMissing] = useState(false);
  const ackRef = useRef<HTMLInputElement>(null);

  const templateSteps = flow.steps.filter((step) => step.output_mode === "template_fill").length;
  const locked = exporting || pending !== null;
  const nameMissing = !name.trim();
  const versionMissing = !version.trim();

  function reset() {
    setPackageId(defaultPackageId(flow.name));
    setIdEdited(false);
    setVersion("1.0.0");
    setName(flow.name);
    setDescription(flow.description ?? "");
    setIncludeTemplates(true);
    setFailure(null);
    setShowProblems(false);
    setPending(null);
    setAcknowledged(false);
    setAckMissing(false);
  }

  function requestOpenChange(next: boolean) {
    if (exporting) return;
    if (!next) reset();
    onOpenChange(next);
  }

  function save(result: PackageExport, id: string) {
    saveBlob(result.blob, result.filename ?? `${id}-${version.trim()}.eneopkg`);
    toast.success(t("flow_editor_tools_package_export_success"));
    requestOpenChange(false);
  }

  async function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (exporting) return;
    if (pending) {
      if (acknowledged) {
        save(pending, packageId);
        return;
      }
      flushSync(() => setAckMissing(true));
      ackRef.current?.focus();
      return;
    }
    if (nameMissing || versionMissing) {
      flushSync(() => setShowProblems(true));
      document.getElementById(formId)?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
      return;
    }
    // The ID that is exported is shown, instead of a refusal of its form.
    const id = normalizePackageId(packageId) || defaultPackageId(name);
    setPackageId(id);
    setExporting(true);
    setFailure(null);
    try {
      const result = await exportFlowPackage(flow.id, {
        package_id: id,
        package_version: version.trim(),
        name: name.trim(),
        description: description.trim(),
        include_templates: includeTemplates
      });
      if (result.omittedMcpAssistants > 0) {
        setPending(result);
        announce(t("flow_editor_tools_package_export_mcp_title"));
      } else {
        save(result, id);
      }
    } catch (error) {
      flushSync(() =>
        setFailure(
          t("flow_editor_tools_package_export_failed", {
            message: packageRefusalMessage(error, t)
          })
        )
      );
      errorRef.current?.focus();
    } finally {
      setExporting(false);
    }
  }

  return (
    <Dialog isOpen={open} onOpenChange={requestOpenChange} purpose="form" width={600}>
      <Layout
        height="auto"
        header={
          <DialogHeader
            title={t("flow_editor_tools_package_export_title")}
            subtitle={t("flow_editor_tools_package_export_description")}
            onOpenChange={requestOpenChange}
          />
        }
        content={
          open ? (
            <LayoutContent>
              <form id={formId} onSubmit={submit} noValidate className="flex flex-col gap-4">
                <TextInput
                  label={t("flow_editor_tools_package_id")}
                  description={t("flow_editor_tools_package_id_help")}
                  value={packageId}
                  onChange={(value) => {
                    setPackageId(value.slice(0, PACKAGE_ID_MAX_LENGTH));
                    setIdEdited(true);
                  }}
                  isDisabled={locked}
                  autoComplete="off"
                />
                <TextInput
                  label={t("flow_editor_tools_package_version")}
                  description={t("flow_editor_tools_package_version_help")}
                  value={version}
                  onChange={(value) => setVersion(value.slice(0, 64))}
                  isRequired
                  isDisabled={locked}
                  autoComplete="off"
                  status={
                    showProblems && versionMissing
                      ? { type: "error", message: t("flow_editor_tools_package_version_required") }
                      : undefined
                  }
                />
                <TextInput
                  label={t("name")}
                  value={name}
                  onChange={(value) => {
                    setName(value);
                    if (!idEdited) setPackageId(defaultPackageId(value));
                  }}
                  isRequired
                  isDisabled={locked}
                  autoComplete="off"
                  status={
                    showProblems && nameMissing
                      ? { type: "error", message: t("flows_new_name_required") }
                      : undefined
                  }
                />
                <TextArea
                  label={t("description")}
                  value={description}
                  onChange={setDescription}
                  isOptional
                  isDisabled={locked}
                  rows={3}
                />
                <div className="bg-ax-sunken rounded-ax-container flex flex-col gap-1 px-4 py-3">
                  <Text type="label" as="p" display="block" className="m-0">
                    {t("flow_editor_tools_package_export_contents_title", {
                      count: flow.steps.length
                    })}
                  </Text>
                  <Text type="supporting" size="sm" as="p" display="block" className="m-0">
                    {t("flow_editor_tools_package_export_contents_includes")}
                  </Text>
                  <Text type="supporting" size="sm" as="p" display="block" className="m-0">
                    {t("flow_editor_tools_package_export_contents_excludes")}
                  </Text>
                </div>
                {templateSteps > 0 ? (
                  <CheckboxInput
                    label={t("flow_editor_tools_package_include_templates")}
                    description={
                      includeTemplates
                        ? t("flow_editor_tools_package_templates_included_help")
                        : t("flow_editor_tools_package_templates_omitted_help")
                    }
                    value={includeTemplates}
                    onChange={setIncludeTemplates}
                    isDisabled={locked}
                  />
                ) : null}
                {pending ? (
                  <Banner
                    status="warning"
                    title={t("flow_editor_tools_package_export_mcp_title")}
                    description={t("flow_editor_tools_package_export_mcp_description", {
                      count: pending.omittedMcpAssistants
                    })}
                    collapsible={false}
                  />
                ) : null}
                {pending ? (
                  <CheckboxInput
                    ref={ackRef}
                    label={t("flow_editor_tools_package_export_mcp_acknowledgement")}
                    value={acknowledged}
                    onChange={(value) => {
                      setAcknowledged(value);
                      if (value) setAckMissing(false);
                    }}
                    isRequired
                    status={
                      ackMissing
                        ? {
                            type: "error",
                            message: t("flow_editor_tools_package_export_mcp_ack_required")
                          }
                        : undefined
                    }
                  />
                ) : null}
                <div ref={errorRef} tabIndex={-1} className="outline-none">
                  {failure ? (
                    <Banner
                      role="alert"
                      status="error"
                      title={t("flow_editor_tools_package_export_failed_title")}
                      description={failure}
                      collapsible={false}
                    />
                  ) : null}
                </div>
              </form>
            </LayoutContent>
          ) : null
        }
        footer={
          open ? (
            <LayoutFooter>
              <div className="flex flex-wrap justify-end gap-2">
                <Button
                  label={t("cancel")}
                  isDisabled={exporting}
                  onClick={() => requestOpenChange(false)}
                />
                <Button
                  type="submit"
                  form={formId}
                  variant="primary"
                  label={
                    pending
                      ? t("flow_editor_tools_package_save")
                      : t("flow_editor_tools_package_export")
                  }
                  isLoading={exporting}
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
