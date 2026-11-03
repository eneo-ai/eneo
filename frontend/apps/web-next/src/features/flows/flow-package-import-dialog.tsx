import { Banner } from "@astryxdesign/core/Banner";
import { IconTile } from "@/components/composites/icon-tile";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { FileInput } from "@astryxdesign/core/FileInput";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { Selector } from "@astryxdesign/core/Selector";
import { Spinner } from "@astryxdesign/core/Spinner";
import { Heading, Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";
import { useQueryClient } from "@tanstack/react-query";
import { FileArchive, PackageOpen, RefreshCw, Upload } from "lucide-react";
import { useRouter } from "@/lib/navigation";
import { useLocale, useTranslations } from "use-intl";
import { useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { FieldMessage } from "./editor/editor-fields";
import { formatBytes } from "@/lib/format";
import { toast } from "@/lib/toast";
import { useSpace } from "@/features/spaces/use-space";
import { flowKeys } from "./flows-api";
import {
  candidateKey,
  createImportPlan,
  fileToBase64,
  importPackage,
  importReadiness,
  initialSelections,
  isPackageFile,
  packageRefusalMessage,
  selectedBindings,
  slotKey,
  TEMPLATE_UPLOAD_MAX_BYTES,
  templateUploadChecksums,
  type BlockingReason,
  type ImportPlan,
  type Resolution,
  type Selections,
  type TemplateUpload
} from "./flow-packages";

const SKIP = "__skip";
const PACKAGE_ACCEPT =
  ".eneopkg,application/vnd.eneo.package+zip,application/zip,application/octet-stream";

type Translate = ReturnType<typeof useTranslations>;

function kindLabel(kind: Resolution["kind"], t: Translate): string {
  return t(`flow_editor_tools_package_kind_${kind}`);
}

function blockingText(reason: BlockingReason, t: Translate): string {
  switch (reason.code) {
    case "template_upload_missing":
      return t("flow_editor_tools_package_template_upload_missing", { name: reason.slotLabel });
    case "template_asset_unsupported":
      return t("flow_editor_tools_package_template_unsupported");
    case "dependency_unsupported":
      return t("flow_editor_tools_package_dependency_unsupported", {
        kind: kindLabel(reason.kind, t)
      });
    case "selected_resource_unavailable":
      return t("flow_editor_tools_package_selected_resource_unavailable", {
        slot: reason.slotLabel
      });
    case "required_mapping_missing":
      return t("flow_editor_tools_package_required_mapping_missing", { slot: reason.slotLabel });
  }
}

/**
 * The space's models that cannot stand in for the package's, each with why, so
 * a model the person expected in the list is explained rather than missing.
 * Models of the other kind (transcription for completion) are left out.
 */
function unusableModels(resolution: Resolution, t: Translate): string[] {
  if (resolution.kind !== "model") return [];
  return (resolution.rejected_candidates ?? []).flatMap(({ candidate, reasons }) => {
    const why = reasons.filter((reason) => reason !== "model_kind_mismatch");
    if (why.length === 0) return [];
    return [
      t("flow_editor_tools_package_model_unusable", {
        model: candidate.label,
        reasons: why.map((reason) => t(`flow_editor_tools_package_model_issue_${reason}`)).join(" ")
      })
    ];
  });
}

function guidanceOf(resolution: Resolution): string | null {
  const guidance = resolution.guidance;
  if (!guidance) return null;
  if (resolution.kind === "model") {
    const model = guidance as NonNullable<Extract<Resolution, { kind: "model" }>["guidance"]>;
    return model.summary ?? model.quality_notes ?? model.minimum_expected_quality ?? null;
  }
  if (resolution.kind === "knowledge") {
    const knowledge = guidance as NonNullable<
      Extract<Resolution, { kind: "knowledge" }>["guidance"]
    >;
    return knowledge.summary ?? knowledge.setup_notes ?? null;
  }
  const template = guidance as NonNullable<
    Extract<Resolution, { kind: "template_asset" }>["guidance"]
  >;
  return template.summary ?? template.replacement_notes ?? template.placeholder_notes ?? null;
}

/** One resource the package needs, and how the person answers it here. */
function Requirement({
  resolution,
  selection,
  disabled,
  templateProblem,
  onSelect,
  onTemplate
}: {
  resolution: Resolution;
  selection: string | null;
  disabled: boolean;
  templateProblem: string | null;
  onSelect: (value: string | null) => void;
  onTemplate: (file: File) => void;
}) {
  const t = useTranslations();
  const titleId = useId();
  const problemId = useId();
  const label = resolution.slot_ref.label;
  const guidance = guidanceOf(resolution);
  const usedBy = resolution.used_by_steps ?? [];
  const sensitivity = resolution.data_sensitivity;
  const template = resolution.kind === "template_asset" ? resolution.template : null;
  const status = template
    ? resolution.install_blocks
      ? t("flow_editor_tools_package_required")
      : t("flow_editor_tools_package_template_ready")
    : resolution.selection_required_for_install
      ? t("flow_editor_tools_package_required")
      : resolution.required
        ? t("flow_editor_tools_package_recommended")
        : t("flow_editor_tools_package_optional");

  const unusable = unusableModels(resolution, t);
  let control: React.ReactNode;
  if (template && resolution.kind === "template_asset") {
    control = (
      <div className="flex flex-col gap-2">
        <Text type="body" size="sm" as="p" display="block" className="m-0 break-all">
          {resolution.upload_filename ?? template.filename}
        </Text>
        <Text type="supporting" size="sm" as="p" display="block" className="m-0">
          {template.asset_path
            ? t("flow_editor_tools_package_template_included")
            : t("flow_editor_tools_package_template_replacement_help")}
        </Text>
        <Text type="supporting" size="sm" as="p" display="block" className="m-0 break-words">
          {t("flow_editor_tools_package_template_expected_fields", {
            fields: template.fields.map((field) => field.name).join(", ")
          })}
        </Text>
        {!template.asset_path ? (
          <FileInput
            label={t("flow_editor_tools_package_template_choose", { name: label })}
            description={t("flow_editor_tools_package_template_file_help")}
            value={null}
            onChange={(picked) => {
              const file = Array.isArray(picked) ? picked[0] : picked;
              if (file) onTemplate(file);
            }}
            accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            isDisabled={disabled}
            status={templateProblem ? { type: "error", message: templateProblem } : undefined}
          />
        ) : null}
      </div>
    );
  } else if (resolution.status === "unsupported") {
    control = (
      <FieldMessage
        id={problemId}
        message={
          resolution.kind === "template_asset"
            ? t("flow_editor_tools_package_template_unsupported")
            : t("flow_editor_tools_package_dependency_unsupported", {
                kind: kindLabel(resolution.kind, t)
              })
        }
      />
    );
  } else if (resolution.suggestions.length === 0) {
    control = (
      <FieldMessage id={problemId} message={t("flow_editor_tools_package_no_candidates")} />
    );
  } else {
    control = (
      <Selector
        label={t("flow_editor_tools_package_local_resource", { slot: label })}
        isLabelHidden
        options={[
          ...(selection === null && resolution.required
            ? [{ value: SKIP, label: t("flow_editor_tools_package_select_local_resource") }]
            : []),
          ...(!resolution.required
            ? [{ value: SKIP, label: t("flow_editor_tools_package_skip_optional") }]
            : []),
          ...resolution.suggestions.map((candidate) => ({
            value: candidateKey(candidate),
            label: candidate.label
          }))
        ]}
        value={selection ?? SKIP}
        onChange={(value) => onSelect(value === SKIP ? null : value)}
        isDisabled={disabled}
        width="100%"
      />
    );
  }

  // What the package needs on the left, the answer on the right; stacked on a phone.
  return (
    <li className="list-none">
      <article aria-labelledby={titleId} className="flex flex-col gap-3 p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:gap-5">
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <Heading
                level={4}
                id={titleId}
                weight="semibold"
                wordBreak="break-word"
                className="min-w-0 text-sm"
              >
                {label}
              </Heading>
              <Token size="sm" label={kindLabel(resolution.kind, t)} />
              <Token
                size="sm"
                color={status === t("flow_editor_tools_package_required") ? "orange" : "default"}
                label={status}
              />
            </div>
            {usedBy.length > 0 ? (
              <Text type="supporting" size="sm" as="p" display="block" className="m-0">
                {t("flow_editor_tools_package_used_by_steps", { steps: usedBy.join(", ") })}
              </Text>
            ) : null}
            {sensitivity ? (
              <Text type="supporting" size="sm" as="p" display="block" className="m-0">
                {[
                  sensitivity.publisher_classification_label
                    ? t("flow_editor_tools_package_data_sensitivity_label", {
                        label: sensitivity.publisher_classification_label
                      })
                    : t("flow_editor_tools_package_data_sensitivity"),
                  sensitivity.notes
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </Text>
            ) : null}
            {guidance ? (
              <Text type="body" size="sm" as="p" display="block" className="m-0 pt-1">
                {t("flow_editor_tools_package_guidance", { text: guidance })}
              </Text>
            ) : null}
          </div>
          <div className="w-full min-w-0 sm:w-72 sm:shrink-0">{control}</div>
        </div>
        {unusable.length > 0 ? (
          <ul className="m-0 flex list-none flex-col gap-1 p-0">
            {unusable.map((line) => (
              <li key={line}>
                <Text type="supporting" size="sm" as="p" display="block" className="m-0">
                  {line}
                </Text>
              </li>
            ))}
          </ul>
        ) : null}
      </article>
    </li>
  );
}

/**
 * "Importera": reads a `.eneopkg` file, shows what the package is and what it
 * needs here, lets the person choose the space's models, knowledge and Word
 * templates for it, and creates it as a draft. Every refusal of the package
 * and every choice still missing is said in words before the import is sent.
 * Controlled by the caller, which renders the trigger.
 */
export function FlowPackageImportDialog({
  open,
  onOpenChange
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const announce = useAnnounce();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { space, routeId } = useSpace();
  const errorRef = useRef<HTMLDivElement>(null);
  const replaceButton = useRef<HTMLButtonElement>(null);
  const replaceInput = useRef<HTMLInputElement>(null);
  const planRequest = useRef(0);
  const [file, setFile] = useState<File | null>(null);
  const [fileProblem, setFileProblem] = useState<string | null>(null);
  const [plan, setPlan] = useState<ImportPlan | null>(null);
  const [selections, setSelections] = useState<Selections>({});
  const [uploads, setUploads] = useState<Record<string, TemplateUpload>>({});
  const [templateProblems, setTemplateProblems] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const readiness = plan ? importReadiness(plan, selections) : null;
  const resolutions = plan?.dependency_resolutions ?? [];
  const omittedMcp = plan?.omissions.find((item) => item.kind === "mcp_attachment")?.count ?? 0;

  function reset() {
    planRequest.current += 1;
    setFile(null);
    setFileProblem(null);
    setPlan(null);
    setSelections({});
    setUploads({});
    setTemplateProblems({});
    setLoading(false);
    setFailure(null);
  }

  function requestOpenChange(next: boolean) {
    if (importing) return;
    if (!next) reset();
    onOpenChange(next);
  }

  async function loadPlan(
    chosen: File,
    nextUploads: Record<string, TemplateUpload>,
    templateSlot?: string
  ) {
    const request = ++planRequest.current;
    setLoading(true);
    setFailure(null);
    announce(t("flow_editor_tools_package_loading_plan"));
    try {
      const next = await createImportPlan(space.id, chosen, Object.values(nextUploads));
      if (request !== planRequest.current) return;
      setPlan(next);
      setSelections((current) => ({ ...initialSelections(next), ...current }));
      setUploads(nextUploads);
      const ready = importReadiness(next, initialSelections(next)).canImport;
      announce(
        [
          t("flow_editor_tools_package_plan_ready", { name: next.package_summary.name }),
          ready ? null : t("flow_editor_tools_package_blocks_import")
        ]
          .filter(Boolean)
          .join(" ")
      );
    } catch (error) {
      if (request !== planRequest.current) return;
      const message = packageRefusalMessage(error, t);
      if (templateSlot) {
        setTemplateProblems((current) => ({
          ...current,
          [templateSlot]: t("flow_editor_tools_package_template_not_applied", { message })
        }));
      } else {
        flushSync(() => setFailure(t("flow_editor_tools_package_import_plan_failed", { message })));
        errorRef.current?.focus();
      }
    } finally {
      if (request === planRequest.current) setLoading(false);
    }
  }

  function choosePackage(picked: File | File[] | null) {
    const chosen = Array.isArray(picked) ? picked[0] : picked;
    if (!chosen) return;
    if (!isPackageFile(chosen)) {
      setFileProblem(t("flow_editor_tools_package_file_invalid"));
      // The drop zone's own status speaks; under the file card it is plain text.
      if (file) announce(t("flow_editor_tools_package_file_invalid"));
      return;
    }
    // The drop zone gives way to the file card: keep focus on its "Byt fil".
    flushSync(() => {
      setFileProblem(null);
      setFile(chosen);
      setPlan(null);
      setSelections({});
      setUploads({});
      setTemplateProblems({});
    });
    replaceButton.current?.focus();
    void loadPlan(chosen, {});
  }

  async function chooseTemplate(slot: string, template: File) {
    if (!file) return;
    setTemplateProblems((current) => ({ ...current, [slot]: "" }));
    if (
      !template.name.toLowerCase().endsWith(".docx") ||
      template.size > TEMPLATE_UPLOAD_MAX_BYTES
    ) {
      setTemplateProblems((current) => ({
        ...current,
        [slot]: t("flow_editor_tools_package_template_file_help")
      }));
      return;
    }
    let content: string;
    try {
      content = await fileToBase64(template);
    } catch {
      setTemplateProblems((current) => ({
        ...current,
        [slot]: t("flow_editor_tools_package_template_read_failed")
      }));
      return;
    }
    await loadPlan(
      file,
      {
        ...uploads,
        [slot]: { template_ref: slot, filename: template.name, content_base64: content }
      },
      slot
    );
  }

  async function submit() {
    if (!file || !plan || !readiness?.canImport || importing || loading) return;
    setImporting(true);
    setFailure(null);
    try {
      const result = await importPackage(space.id, {
        package_base64: await fileToBase64(file),
        expected_content_checksum: plan.content_checksum,
        expected_target_state: plan.target_state,
        selected_bindings: selectedBindings(plan, selections),
        template_uploads: Object.values(uploads),
        expected_template_upload_checksums: templateUploadChecksums(plan)
      });
      toast.success(t("flow_editor_tools_package_import_success", { name: result.flow_name }));
      void queryClient.invalidateQueries({ queryKey: flowKeys.list(space.id) });
      setImporting(false);
      requestOpenChange(false);
      router.push(`/spaces/${routeId}/flows/${result.flow_id}`);
    } catch (error) {
      setImporting(false);
      flushSync(() =>
        setFailure(
          t("flow_editor_tools_package_import_failed", {
            message: packageRefusalMessage(error, t)
          })
        )
      );
      errorRef.current?.focus();
    }
  }

  return (
    <Dialog isOpen={open} onOpenChange={requestOpenChange} purpose="form" width={760}>
      <Layout
        header={
          <DialogHeader
            title={t("flow_editor_tools_package_import_title")}
            subtitle={t("flow_editor_tools_package_import_description")}
            startContent={<IconTile icon={<PackageOpen />} />}
            onOpenChange={requestOpenChange}
          />
        }
        content={
          open ? (
            <LayoutContent>
              <div className="flex flex-col gap-5">
                {file ? (
                  <div className="flex flex-col gap-2">
                    <Card padding={3} className="flex items-center gap-3">
                      <span
                        aria-hidden="true"
                        className="bg-ax-muted text-ax-text-secondary rounded-ax-element flex size-10 shrink-0 items-center justify-center"
                      >
                        <FileArchive className="size-5" />
                      </span>
                      <div className="flex min-w-0 flex-1 flex-col">
                        <Text
                          type="body"
                          size="sm"
                          weight="medium"
                          as="p"
                          display="block"
                          wordBreak="break-all"
                          className="m-0"
                        >
                          {file.name}
                        </Text>
                        <Text type="supporting" size="sm" as="p" display="block" className="m-0">
                          {[
                            formatBytes(file.size, locale),
                            loading ? t("flow_editor_tools_package_loading_plan") : null
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </Text>
                      </div>
                      {loading ? <Spinner size="sm" aria-hidden="true" /> : null}
                      <Button
                        ref={replaceButton}
                        variant="ghost"
                        size="sm"
                        icon={<RefreshCw aria-hidden="true" />}
                        label={t("flow_editor_tools_package_file_replace")}
                        isDisabled={importing}
                        onClick={() => replaceInput.current?.click()}
                      />
                      <input
                        ref={replaceInput}
                        type="file"
                        accept={PACKAGE_ACCEPT}
                        className="hidden"
                        onChange={(event) => {
                          const picked = event.target.files?.[0] ?? null;
                          event.target.value = "";
                          choosePackage(picked);
                        }}
                      />
                    </Card>
                    <FieldMessage message={fileProblem} />
                  </div>
                ) : (
                  <FileInput
                    mode="dropzone"
                    label={t("flow_editor_tools_package_file")}
                    isLabelHidden
                    placeholder={t("flow_package_import_dropzone")}
                    value={null}
                    onChange={choosePackage}
                    accept={PACKAGE_ACCEPT}
                    isDisabled={importing}
                    status={fileProblem ? { type: "error", message: fileProblem } : undefined}
                    width="100%"
                    controlClassName="min-h-56"
                  />
                )}

                {plan ? (
                  <>
                    <MetadataList
                      title={plan.package_summary.name}
                      label={{ position: "start", width: "8rem" }}
                    >
                      {plan.package_summary.description ? (
                        <MetadataListItem label={t("description")}>
                          {plan.package_summary.description}
                        </MetadataListItem>
                      ) : null}
                      <MetadataListItem label={t("flow_editor_tools_package_version")}>
                        {plan.package_version}
                      </MetadataListItem>
                      <MetadataListItem label={t("flow_editor_tools_package_steps")}>
                        {t("flow_editor_tools_package_step_count", {
                          count: plan.package_summary.steps_count
                        })}
                      </MetadataListItem>
                      <MetadataListItem label={t("flow_editor_tools_package_id")}>
                        <span className="font-mono text-xs break-all">{plan.package_id}</span>
                      </MetadataListItem>
                    </MetadataList>

                    {omittedMcp > 0 ? (
                      <Banner
                        status="warning"
                        title={t("flow_editor_tools_package_import_mcp_title")}
                        description={t("flow_editor_tools_package_import_mcp_description", {
                          count: omittedMcp
                        })}
                        collapsible={false}
                      />
                    ) : null}

                    <section className="flex flex-col gap-3">
                      <div className="flex flex-col gap-1">
                        <Heading level={3} weight="semibold" className="text-sm">
                          {t("flow_editor_tools_package_dependency_mapping")}
                        </Heading>
                        <Text type="supporting" size="sm" as="p" display="block" className="m-0">
                          {resolutions.length === 0
                            ? t("flow_editor_tools_package_no_dependencies")
                            : t("flow_editor_tools_package_dependency_mapping_description")}
                        </Text>
                      </div>
                      {readiness &&
                      (readiness.requiresTranscriptionModel ||
                        readiness.blockingReasons.length > 0) ? (
                        <Banner
                          status="error"
                          title={t("flow_editor_tools_package_blocks_import")}
                          description={
                            <ul className="m-0 list-disc pl-5">
                              {readiness.requiresTranscriptionModel ? (
                                <li>
                                  {t(
                                    "flow_editor_tools_package_error_transcription_model_required"
                                  )}
                                </li>
                              ) : null}
                              {readiness.blockingReasons.map((reason) => (
                                <li key={`${reason.slotKey}:${reason.code}`}>
                                  {blockingText(reason, t)}
                                </li>
                              ))}
                            </ul>
                          }
                          collapsible={false}
                        />
                      ) : readiness ? (
                        <Banner
                          status="success"
                          title={
                            readiness.canPublishAfterImport
                              ? t("flow_editor_tools_package_can_publish_after_import")
                              : t("flow_editor_tools_package_needs_review_after_import")
                          }
                          description={
                            [
                              readiness.totalRequired > 0
                                ? t("flow_editor_tools_package_required_progress", {
                                    selected: readiness.selectedRequired,
                                    total: readiness.totalRequired
                                  })
                                : null,
                              readiness.transcriptionModelToChoose
                                ? t("flow_editor_tools_package_transcription_model_to_choose")
                                : null
                            ]
                              .filter(Boolean)
                              .join(" ") || undefined
                          }
                          collapsible={false}
                        />
                      ) : null}
                      {resolutions.length > 0 ? (
                        <ul className="border-ax-border divide-ax-border rounded-ax-container m-0 flex flex-col divide-y border p-0">
                          {resolutions.map((resolution) => {
                            const key = slotKey(resolution);
                            return (
                              <Requirement
                                key={key}
                                resolution={resolution}
                                selection={selections[key] ?? null}
                                disabled={importing || loading}
                                templateProblem={templateProblems[key] || null}
                                onSelect={(value) =>
                                  setSelections((current) => ({ ...current, [key]: value }))
                                }
                                onTemplate={(template) => void chooseTemplate(key, template)}
                              />
                            );
                          })}
                        </ul>
                      ) : null}
                    </section>
                  </>
                ) : null}

                <div ref={errorRef} tabIndex={-1} className="outline-none">
                  {failure ? (
                    <Banner
                      role="alert"
                      status="error"
                      title={t("flow_editor_tools_package_import_failed_title")}
                      description={failure}
                      collapsible={false}
                    />
                  ) : null}
                </div>
              </div>
            </LayoutContent>
          ) : null
        }
        footer={
          open ? (
            <LayoutFooter>
              <div className="flex flex-wrap justify-end gap-2">
                <Button
                  label={t("cancel")}
                  isDisabled={importing}
                  onClick={() => requestOpenChange(false)}
                />
                <Button
                  variant="primary"
                  label={t("flow_editor_tools_package_import_as_draft")}
                  icon={<Upload aria-hidden="true" />}
                  isDisabled={!plan || !readiness?.canImport || loading}
                  isLoading={importing}
                  isInterruptible
                  onClick={() => void submit()}
                />
              </div>
            </LayoutFooter>
          ) : null
        }
      />
    </Dialog>
  );
}
