import { Banner } from "@astryxdesign/core/Banner";
import { IconTile } from "@/components/composites/icon-tile";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { FileInput } from "@astryxdesign/core/FileInput";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { Selector } from "@astryxdesign/core/Selector";
import { Spinner } from "@astryxdesign/core/Spinner";
import { Heading, Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";
import { useQueryClient } from "@tanstack/react-query";
import { FileArchive, PackageOpen, RefreshCw, Upload } from "lucide-react";
import { useRouter } from "@/lib/navigation";
import { useLocale, useTranslations } from "use-intl";
import { useEffect, useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { FieldMessage } from "./editor/editor-fields";
import { formatBytes } from "@/lib/format";
import { usePhoneScreen } from "@/lib/hooks/use-media-match";
import { toast } from "@/lib/toast";
import { useSpace } from "@/features/spaces/use-space";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
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
  type ImportReadiness,
  type Resolution,
  type Selections,
  type TemplateUpload
} from "./flow-packages";

const STEP_KEY = /^step_(\d+)$/;
const PACKAGE_ACCEPT =
  ".eneopkg,application/vnd.eneo.package+zip,application/zip,application/octet-stream";

type Translate = ReturnType<typeof useTranslations>;

function kindLabel(kind: Resolution["kind"], t: Translate): string {
  return t(`flow_editor_tools_package_kind_${kind}`);
}

/**
 * What a model or knowledge source does here ("Språkmodell"), which the row is
 * headed by: the package's own label names what the exporter used. A Word
 * template is headed by its file, so it has none.
 */
function roleLabel(resolution: Resolution, t: Translate): string | null {
  if (resolution.kind === "model") {
    return t(`flow_package_import_role_${resolution.model_kind}`);
  }
  return resolution.kind === "knowledge" ? t("flow_package_import_role_knowledge") : null;
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

/**
 * What no answer in the rows below can lift. A choice or Word template still
 * to be given is a step ahead, not a problem.
 */
function realBlockers(readiness: ImportReadiness, plan: ImportPlan): BlockingReason[] {
  return readiness.blockingReasons.filter((reason) => {
    const resolution = plan.dependency_resolutions?.find(
      (item) => slotKey(item) === reason.slotKey
    );
    if (reason.code === "required_mapping_missing") return !resolution?.suggestions.length;
    if (reason.code === "template_upload_missing") {
      return resolution?.kind !== "template_asset" || Boolean(resolution.template?.asset_path);
    }
    return true;
  });
}

/**
 * The steps a resource is used by. The plan has no step names, only the
 * package's keys (`step_3`): those read as numbers, a run of them as "Steg 3–8".
 */
function usedByText(steps: readonly string[], t: Translate): string {
  const runs: [number, number][] = [];
  const numbers = steps.flatMap((step) => STEP_KEY.exec(step)?.[1] ?? []).map(Number);
  for (const number of numbers.sort((a, b) => a - b)) {
    const last = runs.at(-1);
    if (last && number === last[1] + 1) last[1] = number;
    else runs.push([number, number]);
  }
  const numbered = runs.map(([from, to]) => (from === to ? `${from}` : `${from}–${to}`)).join(", ");
  return [
    ...(numbered ? [t("flows_step_label_unnamed", { order: numbered })] : []),
    ...steps.filter((step) => !STEP_KEY.test(step))
  ].join(", ");
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
  const role = roleLabel(resolution, t);
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
  const controlRef = useRef<HTMLDivElement>(null);
  // A refused Word file is said under its field, which may be below the fold: go there.
  useEffect(() => {
    if (!templateProblem) return;
    controlRef.current?.scrollIntoView({ block: "nearest" });
    controlRef.current
      ?.querySelector<HTMLElement>('[aria-invalid="true"]')
      ?.focus({ preventScroll: true });
  }, [templateProblem]);
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
        placeholder={t(
          resolution.required
            ? "flow_editor_tools_package_select_local_resource"
            : "flow_editor_tools_package_skip_optional"
        )}
        options={resolution.suggestions.map((candidate) => ({
          value: candidateKey(candidate),
          label: candidate.label
        }))}
        hasClear
        value={selection}
        onChange={onSelect}
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
                level={5}
                id={titleId}
                weight="medium"
                wordBreak="break-word"
                className="min-w-0 text-sm"
              >
                {role ?? label}
              </Heading>
              {role ? null : <Token size="sm" label={kindLabel(resolution.kind, t)} />}
              <Token
                size="sm"
                color={status === t("flow_editor_tools_package_required") ? "orange" : "default"}
                label={status}
              />
            </div>
            {role ? (
              <Text
                type="supporting"
                size="sm"
                as="p"
                display="block"
                wordBreak="break-word"
                className="m-0"
              >
                {t("flow_package_import_built_with", { name: label })}
              </Text>
            ) : null}
            {usedBy.length > 0 ? (
              <Text type="supporting" size="sm" as="p" display="block" className="m-0">
                {t("flow_editor_tools_package_used_by_steps", { steps: usedByText(usedBy, t) })}
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
          <div ref={controlRef} className="w-full min-w-0 sm:w-72 sm:shrink-0">
            {control}
          </div>
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
  // A phone gets the whole screen and a header without the tile, which would wrap the title and
  // leave the list of what the package needs too little height (320 × 256 at 400 % zoom).
  const whole = usePhoneScreen();
  const [file, setFile] = useState<File | null>(null);
  const [fileProblem, setFileProblem] = useState<string | null>(null);
  const [plan, setPlan] = useState<ImportPlan | null>(null);
  const [selections, setSelections] = useState<Selections>({});
  const [uploads, setUploads] = useState<Record<string, TemplateUpload>>({});
  const [templateProblems, setTemplateProblems] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  /** A refusal, and whether reading the package (plan) or importing it failed. */
  const [failure, setFailure] = useState<{ stage: "plan" | "import"; message: string } | null>(
    null
  );
  const [confirmDiscard, setConfirmDiscard] = useState(false);

  const readiness = plan ? importReadiness(plan, selections) : null;
  const blockers = plan && readiness ? realBlockers(readiness, plan) : [];
  const refused = blockers.length > 0 || readiness?.requiresTranscriptionModel === true;
  const resolutions = plan?.dependency_resolutions ?? [];
  const omittedMcp = plan?.omissions.find((item) => item.kind === "mcp_attachment")?.count ?? 0;
  const needsReview = readiness?.canImport === true && !readiness.canPublishAfterImport;
  // Audio settings the package leaves behind. A review ahead is said beside the buttons instead,
  // so the rows do not move when the last choice is made.
  const audioNote = !refused && readiness?.takesAudio === true;
  // Choices the person made would be lost by closing: ask first.
  const initial = plan ? initialSelections(plan) : {};
  const hasChoices =
    Object.keys(uploads).length > 0 ||
    Object.entries(selections).some(([key, value]) => value !== (initial[key] ?? null));

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

  function close() {
    setConfirmDiscard(false);
    reset();
    onOpenChange(false);
  }

  function requestOpenChange(next: boolean) {
    if (importing) return;
    if (next) onOpenChange(true);
    else if (hasChoices) setConfirmDiscard(true);
    else close();
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
      const found = importReadiness(next, initialSelections(next));
      announce(
        [
          t("flow_editor_tools_package_plan_ready", { name: next.package_summary.name }),
          found.requiresTranscriptionModel || realBlockers(found, next).length > 0
            ? t("flow_editor_tools_package_blocks_import")
            : null
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
        flushSync(() => setFailure({ stage: "plan", message }));
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
      close();
      router.push(`/spaces/${routeId}/flows/${result.flow_id}`);
    } catch (error) {
      setImporting(false);
      flushSync(() => setFailure({ stage: "import", message: packageRefusalMessage(error, t) }));
      errorRef.current?.focus();
    }
  }

  return (
    <>
      <Dialog
        isOpen={open}
        onOpenChange={requestOpenChange}
        purpose="form"
        variant={whole ? "fullscreen" : "standard"}
        width={760}
        maxHeight="85dvh"
      >
        <Layout
          header={
            <DialogHeader
              title={t("flow_editor_tools_package_import_title")}
              subtitle={t("flow_editor_tools_package_import_description")}
              startContent={whole ? undefined : <IconTile icon={<PackageOpen />} />}
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
                        <IconTile icon={<FileArchive />} />
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
                              plan
                                ? `${t("flow_editor_tools_package_version")} ${plan.package_version}`
                                : null,
                              plan
                                ? t("flow_editor_tools_package_step_count", {
                                    count: plan.package_summary.steps_count
                                  })
                                : null,
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
                      controlClassName="phone:min-h-32 min-h-56"
                    />
                  )}

                  {plan ? (
                    <>
                      <div className="flex flex-col gap-1">
                        <Heading level={3} weight="semibold" wordBreak="break-word">
                          {plan.package_summary.name}
                        </Heading>
                        {plan.package_summary.description ? (
                          <Text type="body" size="sm" as="p" display="block" className="m-0">
                            {plan.package_summary.description}
                          </Text>
                        ) : null}
                      </div>

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

                      {refused ? (
                        <Banner
                          status="error"
                          title={t("flow_editor_tools_package_blocks_import")}
                          description={
                            <ul className="m-0 list-disc pl-5">
                              {readiness?.requiresTranscriptionModel ? (
                                <li>
                                  {t(
                                    "flow_editor_tools_package_error_transcription_model_required"
                                  )}
                                </li>
                              ) : null}
                              {blockers.map((reason) => (
                                <li key={`${reason.slotKey}:${reason.code}`}>
                                  {blockingText(reason, t)}
                                </li>
                              ))}
                            </ul>
                          }
                          collapsible={false}
                        />
                      ) : audioNote ? (
                        <Banner
                          status="info"
                          title={t("flow_package_import_audio_title")}
                          description={
                            readiness?.transcriptionModelToChoose
                              ? t("flow_editor_tools_package_transcription_model_to_choose")
                              : t("flow_package_import_audio_body")
                          }
                          collapsible={false}
                        />
                      ) : null}

                      {resolutions.length > 0 ? (
                        <section className="flex flex-col gap-3">
                          <div className="flex flex-col gap-1">
                            <Heading level={4} weight="semibold" className="text-sm">
                              {t("flow_editor_tools_package_dependency_mapping")}
                            </Heading>
                            <Text
                              type="supporting"
                              size="sm"
                              as="p"
                              display="block"
                              className="m-0"
                            >
                              {t("flow_editor_tools_package_dependency_mapping_description")}
                            </Text>
                          </div>
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
                        </section>
                      ) : null}
                    </>
                  ) : null}

                  <div ref={errorRef} tabIndex={-1} className="outline-none">
                    {failure ? (
                      <Banner
                        role="alert"
                        status="error"
                        title={
                          failure.stage === "plan"
                            ? t("flow_package_import_plan_failed_title")
                            : t("flow_editor_tools_package_import_failed_title")
                        }
                        description={failure.message}
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
                <div className="flex flex-wrap items-center justify-end gap-x-4 gap-y-2">
                  {/* Beside the buttons, so why importing waits stays in view however far the list
                    is scrolled. */}
                  <p role="status" className="text-ax-text-secondary m-0 mr-auto text-sm">
                    {refused
                      ? t("flow_package_import_footer_blocked")
                      : [
                          readiness && readiness.totalRequired > 0
                            ? t("flow_editor_tools_package_required_progress", {
                                selected: readiness.selectedRequired,
                                total: readiness.totalRequired
                              })
                            : readiness?.canImport
                              ? t("flow_package_import_footer_ready")
                              : null,
                          needsReview
                            ? t("flow_editor_tools_package_needs_review_after_import")
                            : null
                        ]
                          .filter(Boolean)
                          .join(" ")}
                  </p>
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
                </div>
              </LayoutFooter>
            ) : null
          }
        />
      </Dialog>
      <ConfirmDialogControlled
        open={confirmDiscard}
        onOpenChange={setConfirmDiscard}
        title={t("flow_package_import_discard_title")}
        description={t("flow_package_import_discard_description")}
        confirmLabel={t("flow_package_import_discard_confirm")}
        onConfirm={() => {
          // The confirmation hands focus back into this dialog first, so that closing this one
          // then returns it to the button that opened it.
          flushSync(() => setConfirmDiscard(false));
          close();
        }}
      />
    </>
  );
}
