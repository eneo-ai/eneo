<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { EneoError, type FlowPackageDependencyResolution, type Eneo } from "@eneo/eneo-js";
  import {
    AlertTriangle,
    CheckCircle2,
    FileArchive,
    FileDown,
    Loader2,
    PackageOpen,
    RefreshCw,
    Upload,
    UploadCloud
  } from "lucide-svelte";
  import { toast } from "$lib/components/toast";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { getFlowsManager } from "$lib/features/flows/FlowsManager";
  import {
    buildSelectedFlowPackageResourceBindings,
    createInitialFlowPackageImportSelections,
    encodeFlowPackageFileToBase64,
    getFlowPackageCandidateKey,
    getFlowPackageImportReadiness,
    getFlowPackageResolutionSlotKey,
    getFlowPackageResolutionSlotLabel,
    mapFlowPackageImportError,
    type FlowPackageCandidate,
    type FlowPackageImportSelectionState
  } from "$lib/features/flows/flowPackageTransfer";
  import { m } from "$lib/paraglide/messages";

  let {
    eneo,
    spaceId,
    spaceRouteId
  }: {
    eneo: Eneo;
    spaceId: string;
    spaceRouteId: string;
  } = $props();

  const flowsManager = getFlowsManager();
  const SKIP_OPTIONAL_VALUE = "__skip_optional__";
  const PACKAGE_EXTENSION = ".eneo-flowpkg";
  const FILE_ACCEPT = ".eneo-flowpkg,application/octet-stream,application/zip";

  let open = $state(false);
  let selectedFile = $state<File | null>(null);
  let plan = $state<Awaited<ReturnType<Eneo["flows"]["packages"]["createImportPlan"]>> | null>(
    null
  );
  let selections = $state<FlowPackageImportSelectionState>({});
  let loadError = $state<string | null>(null);
  let importError = $state<string | null>(null);
  let loadingPlan = $state(false);
  let importing = $state(false);
  let isDragging = $state(false);
  let fileInputElement = $state<HTMLInputElement | null>(null);
  let planRequestId = 0;
  let planAbortController: AbortController | null = null;

  const readiness = $derived(plan ? getFlowPackageImportReadiness(plan, selections) : null);
  const dependencyResolutions = $derived(plan?.dependency_resolutions ?? []);
  const canSubmit = $derived(
    !!selectedFile && !!plan && !!readiness?.canImport && !importing && !loadingPlan
  );

  function handleOpenChange(next: boolean) {
    open = next;
    if (!next) reset();
  }

  function reset() {
    cancelPlanLoad();
    selectedFile = null;
    plan = null;
    selections = {};
    loadError = null;
    importError = null;
    loadingPlan = false;
    importing = false;
    isDragging = false;
  }

  function isValidFlowPackage(file: File): boolean {
    return file.name.toLowerCase().endsWith(PACKAGE_EXTENSION);
  }

  async function consumeFile(file: File) {
    if (!isValidFlowPackage(file)) {
      toast.error(m.flow_package_dropzone_invalid_format());
      return;
    }
    cancelPlanLoad();
    selectedFile = file;
    plan = null;
    selections = {};
    loadError = null;
    importError = null;
    const controller = new AbortController();
    const requestId = ++planRequestId;
    planAbortController = controller;
    await loadImportPlan(file, requestId, controller.signal);
  }

  async function handleFileChange(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const [file] = input.files ? Array.from(input.files) : [];
    // Clear so re-picking the same file still fires change.
    input.value = "";
    if (file) await consumeFile(file);
  }

  function cancelPlanLoad() {
    planRequestId += 1;
    planAbortController?.abort();
    planAbortController = null;
    loadingPlan = false;
  }

  function isCurrentPlanLoad(requestId: number, signal: AbortSignal) {
    return requestId === planRequestId && !signal.aborted;
  }

  async function loadImportPlan(file: File, requestId: number, signal: AbortSignal) {
    loadingPlan = true;
    try {
      const nextPlan = await eneo.flows.packages.createImportPlan({ spaceId, file, signal });
      if (!isCurrentPlanLoad(requestId, signal)) return;
      plan = nextPlan;
      selections = createInitialFlowPackageImportSelections(nextPlan);
    } catch (error) {
      if (!isCurrentPlanLoad(requestId, signal)) return;
      const message =
        mapFlowPackageImportError(error) ??
        (error instanceof EneoError ? error.getReadableMessage() : String(error));
      loadError = m.flow_package_import_plan_failed({ message });
    } finally {
      if (isCurrentPlanLoad(requestId, signal)) {
        loadingPlan = false;
        planAbortController = null;
      }
    }
  }

  async function importPackage() {
    if (!selectedFile || !plan) {
      importError = m.flow_package_missing_file();
      return;
    }
    if (!readiness?.canImport) {
      importError = m.flow_package_blocks_import();
      return;
    }

    importing = true;
    importError = null;
    try {
      const selectedBindings = buildSelectedFlowPackageResourceBindings(plan, selections);
      const packageBase64 = await encodeFlowPackageFileToBase64(selectedFile);
      const result = await eneo.flows.packages.importDraft({
        spaceId,
        packageBase64,
        expectedContentChecksum: plan.content_checksum,
        expectedTargetState: plan.target_state,
        selectedBindings
      });
      await flowsManager.refreshFlows();
      toast.success(m.flow_package_import_success());
      open = false;
      reset();
      goto(resolve(`/spaces/${spaceRouteId}/flows/${result.flow_id}`));
    } catch (error) {
      const message =
        mapFlowPackageImportError(error) ??
        (error instanceof EneoError ? error.getReadableMessage() : String(error));
      importError = m.flow_package_import_failed({ message });
    } finally {
      importing = false;
    }
  }

  function setSelection(slotKey: string, value: string | undefined) {
    selections = {
      ...selections,
      [slotKey]: value && value !== SKIP_OPTIONAL_VALUE ? value : null
    };
  }

  function selectedValue(slotKey: string): string {
    return selections[slotKey] ?? SKIP_OPTIONAL_VALUE;
  }

  function requirementKindLabel(kind: FlowPackageDependencyResolution["kind"]) {
    switch (kind) {
      case "model":
        return m.flow_package_kind_model();
      case "knowledge":
        return m.flow_package_kind_knowledge();
      case "template_asset":
        return m.flow_package_kind_template_asset();
      default:
        return assertNever(kind);
    }
  }

  function assertNever(value: never): never {
    throw new Error(`Unsupported flow package dependency kind: ${value}`);
  }

  function requirementCountLabel(count: number) {
    if (count === 0) return m.flow_package_requirement_count_zero();
    if (count === 1) return m.flow_package_requirement_count({ count: String(count) });
    return m.flow_package_requirement_count_plural({ count: String(count) });
  }

  function guidanceText(resolution: FlowPackageDependencyResolution): string | null {
    if (resolution.kind === "model") {
      return (
        resolution.guidance?.summary ??
        resolution.guidance?.quality_notes ??
        resolution.guidance?.minimum_expected_quality ??
        null
      );
    }
    if (resolution.kind === "knowledge") {
      return resolution.guidance?.summary ?? resolution.guidance?.setup_notes ?? null;
    }
    return (
      resolution.guidance?.summary ??
      resolution.guidance?.replacement_notes ??
      resolution.guidance?.placeholder_notes ??
      null
    );
  }

  function selectedCandidateLabel(
    resolution: FlowPackageDependencyResolution,
    slotKey: string
  ): string {
    const selected = selectedValue(slotKey);
    if (selected === SKIP_OPTIONAL_VALUE) return m.flow_package_select_local_resource();
    for (const candidate of resolution.suggestions as FlowPackageCandidate[]) {
      if (getFlowPackageCandidateKey(candidate) === selected) return candidate.label;
    }
    return m.flow_package_select_local_resource();
  }

  function triggerFilePicker() {
    fileInputElement?.click();
  }

  function handleDragEnter(event: DragEvent) {
    event.preventDefault();
    if (importing) return;
    isDragging = true;
  }

  function handleDragOver(event: DragEvent) {
    event.preventDefault();
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = "copy";
    }
    if (importing) return;
    isDragging = true;
  }

  function handleDragLeave(event: DragEvent) {
    const target = event.currentTarget as HTMLElement;
    const next = event.relatedTarget as Node | null;
    if (!next || !target.contains(next)) {
      isDragging = false;
    }
  }

  async function handleDrop(event: DragEvent) {
    event.preventDefault();
    isDragging = false;
    if (importing) return;
    const [file] = Array.from(event.dataTransfer?.files ?? []);
    if (file) await consumeFile(file);
  }
</script>

<Button variant="outline" onclick={() => (open = true)}>
  <Upload class="size-4" />
  {m.flow_package_import_button()}
</Button>

<Dialog.Root {open} onOpenChange={handleOpenChange}>
  <Dialog.Content
    class="grid max-h-[92vh] !max-w-2xl grid-rows-[auto_minmax(0,1fr)_auto] !gap-0 overflow-hidden !p-0 lg:!max-w-3xl"
  >
    <header class="border-default flex items-start gap-3 border-b px-5 py-4 sm:px-6 sm:py-5">
      <div
        class="bg-accent-default/10 text-accent-default flex size-10 shrink-0 items-center justify-center rounded-xl"
        aria-hidden="true"
      >
        <PackageOpen class="size-5" />
      </div>
      <div class="min-w-0 flex-1">
        <Dialog.Title class="text-primary text-base font-semibold tracking-tight">
          {m.flow_package_import()}
        </Dialog.Title>
        <Dialog.Description class="text-secondary mt-1 max-w-[64ch] text-sm leading-relaxed">
          {m.flow_package_import_description()}
        </Dialog.Description>
      </div>
    </header>

    <div class="overflow-y-auto px-5 py-5 sm:px-6">
      <Input
        bind:ref={fileInputElement}
        id="flow-package-file-input"
        type="file"
        accept={FILE_ACCEPT}
        disabled={importing}
        onchange={handleFileChange}
        class="sr-only"
      />

      {#if !selectedFile}
        <label
          for="flow-package-file-input"
          class="bg-muted/30 border-default/70 group hover:border-accent-default/60 hover:bg-accent-default/5 focus-within:border-accent-default focus-within:ring-accent-default/25 flex min-h-[220px] cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed px-6 py-8 text-center transition-colors duration-150 ease-out focus-within:ring-2 sm:min-h-[260px] {isDragging
            ? '!border-accent-default !bg-accent-default/10 ring-accent-default/30 ring-2'
            : ''}"
          ondragenter={handleDragEnter}
          ondragover={handleDragOver}
          ondragleave={handleDragLeave}
          ondrop={handleDrop}
        >
          <div
            class="bg-secondary/60 text-secondary group-hover:bg-accent-default/15 group-hover:text-accent-default flex size-12 shrink-0 items-center justify-center rounded-2xl transition-colors duration-150 ease-out {isDragging
              ? '!bg-accent-default/15 !text-accent-default'
              : ''}"
            aria-hidden="true"
          >
            {#if isDragging}
              <FileDown class="size-6" />
            {:else}
              <UploadCloud class="size-6" />
            {/if}
          </div>
          <div class="flex flex-col gap-1">
            <p class="text-primary text-sm leading-snug font-medium">
              {isDragging
                ? m.flow_package_dropzone_dragging()
                : m.flow_package_dropzone_idle_title()}
            </p>
            {#if !isDragging}
              <p class="text-secondary text-sm leading-snug">
                {m.flow_package_dropzone_idle_action()}
              </p>
            {/if}
          </div>
          <p class="text-muted text-xs">{m.flow_package_dropzone_format_hint()}</p>
        </label>
      {:else}
        <div class="flex flex-col gap-5">
          <div
            class="border-default bg-primary flex items-center gap-3 rounded-xl border px-3 py-2.5 shadow-xs"
          >
            <div
              class="bg-accent-default/10 text-accent-default flex size-10 shrink-0 items-center justify-center rounded-lg"
              aria-hidden="true"
            >
              <FileArchive class="size-5" />
            </div>
            <div class="min-w-0 flex-1">
              <p class="text-primary truncate text-sm font-medium" title={selectedFile.name}>
                {selectedFile.name}
              </p>
              <p class="text-muted mt-0.5 truncate text-xs tabular-nums" aria-live="polite">
                {formatBytes(selectedFile.size)}
                {#if loadingPlan}
                  <span aria-hidden="true" class="mx-1">·</span>{m.flow_package_loading_plan()}
                {/if}
              </p>
            </div>
            {#if loadingPlan}
              <Loader2 class="text-muted size-4 shrink-0 animate-spin" aria-hidden="true" />
            {/if}
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onclick={triggerFilePicker}
              disabled={importing}
            >
              <RefreshCw class="size-3.5" />
              {m.flow_package_file_replace()}
            </Button>
          </div>

          {#if loadError}
            <Alert.Root variant="destructive">
              <AlertTriangle class="size-4" />
              <Alert.Title>{m.error()}</Alert.Title>
              <Alert.Description>{loadError}</Alert.Description>
            </Alert.Root>
          {/if}

          {#if plan}
            <Card.Root>
              <Card.Content class="grid gap-4 p-4 sm:p-5">
                <div>
                  <h3 class="text-primary text-[15px] font-semibold tracking-tight">
                    {plan.package_summary.name}
                  </h3>
                  {#if plan.package_summary.description}
                    <p class="text-secondary mt-1.5 max-w-[60ch] text-sm leading-relaxed">
                      {plan.package_summary.description}
                    </p>
                  {/if}
                </div>

                <dl class="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
                  <div>
                    <dt class="text-muted text-xs font-medium tracking-wide uppercase">
                      {m.flow_package_package_version()}
                    </dt>
                    <dd class="text-primary mt-1 font-medium tabular-nums">
                      {plan.package_version}
                    </dd>
                  </div>
                  <div>
                    <dt class="text-muted text-xs font-medium tracking-wide uppercase">
                      {m.flow_package_requirements_label()}
                    </dt>
                    <dd class="text-primary mt-1 font-medium tabular-nums">
                      {requirementCountLabel(plan.package_summary.requirements_count)}
                    </dd>
                  </div>
                </dl>

                <div class="flex flex-wrap items-center gap-2">
                  <Badge variant="secondary" class="h-5 font-medium tabular-nums">
                    {m.flow_package_step_count({
                      count: String(plan.package_summary.steps_count)
                    })}
                  </Badge>
                  <Badge variant="outline" class="text-muted h-5 font-mono text-xs">
                    {plan.package_id}
                  </Badge>
                </div>
              </Card.Content>
            </Card.Root>

            <section class="flex flex-col gap-3">
              <header class="flex flex-col gap-1">
                <h3 class="text-primary text-sm font-semibold">
                  {m.flow_package_dependency_mapping()}
                </h3>
                <p class="text-secondary max-w-[64ch] text-sm leading-relaxed">
                  {m.flow_package_dependency_mapping_description()}
                </p>
              </header>

              {#if readiness}
                {#if readiness.requiresTranscriptionModel || readiness.blockingReasons.length > 0}
                  <Alert.Root variant="destructive">
                    <AlertTriangle class="size-4" />
                    <Alert.Title>{m.flow_package_blocks_import()}</Alert.Title>
                    <Alert.Description>
                      <ul class="ml-4 list-disc">
                        {#if readiness.requiresTranscriptionModel}
                          <li>{m.flow_package_error_transcription_model_required()}</li>
                        {/if}
                        {#each readiness.blockingReasons as reason (`${reason.slotKey}:${reason.code}`)}
                          <li>
                            {#if reason.code === "template_asset_unsupported"}
                              {m.flow_package_template_unsupported()}
                            {:else if reason.code === "dependency_unsupported"}
                              {m.flow_package_dependency_unsupported({
                                kind: requirementKindLabel(reason.kind)
                              })}
                            {:else if reason.code === "selected_resource_unavailable"}
                              {m.flow_package_selected_resource_unavailable()}
                            {:else}
                              {m.flow_package_required_mapping_missing({
                                slot: reason.slotLabel
                              })}
                            {/if}
                          </li>
                        {/each}
                      </ul>
                    </Alert.Description>
                  </Alert.Root>
                {:else}
                  <div
                    class="border-positive-default/30 bg-positive-dimmer/40 flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2"
                    aria-live="polite"
                  >
                    <div class="flex items-center gap-2 text-sm">
                      <CheckCircle2
                        class="text-positive-stronger size-4 shrink-0"
                        aria-hidden="true"
                      />
                      <span class="text-primary font-medium">
                        {readiness.canPublishAfterImport
                          ? m.flow_package_can_publish_after_import()
                          : m.flow_package_needs_review_after_import()}
                      </span>
                    </div>
                    {#if readiness.totalRequiredCount > 0}
                      <span class="text-secondary text-xs tabular-nums">
                        {m.flow_package_required_progress({
                          selected: String(readiness.selectedRequiredCount),
                          total: String(readiness.totalRequiredCount)
                        })}
                      </span>
                    {/if}
                  </div>
                {/if}
              {/if}

              {#if dependencyResolutions.length === 0}
                <p
                  class="border-default/70 text-muted rounded-xl border border-dashed px-4 py-6 text-center text-sm"
                >
                  {m.flow_package_no_dependencies()}
                </p>
              {:else}
                <ul
                  class="border-default bg-primary divide-default divide-y overflow-hidden rounded-xl border"
                >
                  {#each dependencyResolutions as resolution (getFlowPackageResolutionSlotKey(resolution))}
                    {@const slotKey = getFlowPackageResolutionSlotKey(resolution)}
                    {@const slotLabel = getFlowPackageResolutionSlotLabel(resolution)}
                    {@const guide = guidanceText(resolution)}
                    {@const usedBySteps = resolution.used_by_steps ?? []}
                    <li
                      class="flex flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-start sm:justify-between sm:gap-5"
                    >
                      <div class="min-w-0 flex-1">
                        <div class="flex flex-wrap items-center gap-2">
                          <h4 class="text-primary text-sm font-semibold">{slotLabel}</h4>
                          <Badge variant="secondary" class="h-5 font-medium">
                            {requirementKindLabel(resolution.kind)}
                          </Badge>
                          {#if resolution.selection_required_for_install}
                            <span
                              class="border-warning-default/40 bg-warning-dimmer/50 text-warning-stronger inline-flex h-5 items-center gap-1 rounded-full border px-1.5 text-xs font-medium"
                            >
                              <span
                                aria-hidden="true"
                                class="bg-warning-stronger size-1.5 rounded-full"
                              ></span>
                              {m.flow_package_required()}
                            </span>
                          {:else if resolution.required}
                            <span
                              class="border-default/70 text-muted inline-flex h-5 items-center rounded-full border px-1.5 text-xs font-medium"
                            >
                              {m.flow_package_recommended_setup()}
                            </span>
                          {:else}
                            <span
                              class="border-default/70 text-muted inline-flex h-5 items-center rounded-full border px-1.5 text-xs font-medium"
                            >
                              {m.flow_package_optional()}
                            </span>
                          {/if}
                        </div>
                        {#if usedBySteps.length > 0}
                          <p class="text-muted mt-1.5 text-xs">
                            {m.flow_package_used_by_steps({
                              steps: usedBySteps.join(", ")
                            })}
                          </p>
                        {/if}
                        {#if resolution.data_sensitivity}
                          <p class="text-muted mt-0.5 text-xs">
                            {#if resolution.data_sensitivity.publisher_classification_label}
                              {m.flow_package_data_sensitivity_label({
                                label: resolution.data_sensitivity.publisher_classification_label
                              })}
                            {:else}
                              {m.flow_package_data_sensitivity()}
                            {/if}
                            {#if resolution.data_sensitivity.notes}
                              <span aria-hidden="true" class="mx-1">·</span>
                              {resolution.data_sensitivity.notes}
                            {/if}
                          </p>
                        {/if}
                        {#if guide}
                          <p class="text-secondary mt-2 max-w-[60ch] text-sm leading-relaxed">
                            <span class="text-primary font-medium"
                              >{m.flow_package_guidance()}:</span
                            >
                            {guide}
                          </p>
                        {/if}
                      </div>

                      <div class="w-full sm:w-72 sm:shrink-0">
                        {#if resolution.status === "unsupported"}
                          <div class="text-destructive flex items-start gap-1.5 text-sm">
                            <AlertTriangle class="mt-0.5 size-4 shrink-0" />
                            <span>
                              {#if resolution.kind === "template_asset"}
                                {m.flow_package_template_unsupported()}
                              {:else}
                                {m.flow_package_dependency_unsupported({
                                  kind: requirementKindLabel(resolution.kind)
                                })}
                              {/if}
                            </span>
                          </div>
                        {:else if resolution.suggestions.length === 0}
                          <div class="text-destructive flex items-start gap-1.5 text-sm">
                            <AlertTriangle class="mt-0.5 size-4 shrink-0" />
                            <span>{m.flow_package_no_candidates()}</span>
                          </div>
                        {:else}
                          <Select.Root
                            type="single"
                            value={selectedValue(slotKey)}
                            disabled={importing}
                            onValueChange={(value) => setSelection(slotKey, value)}
                          >
                            <Select.Trigger class="w-full">
                              {selectedValue(slotKey) === SKIP_OPTIONAL_VALUE
                                ? m.flow_package_select_local_resource()
                                : selectedCandidateLabel(resolution, slotKey)}
                            </Select.Trigger>
                            <Select.Content>
                              {#if !resolution.required}
                                <Select.Item
                                  value={SKIP_OPTIONAL_VALUE}
                                  label={m.flow_package_skip_optional()}
                                >
                                  {m.flow_package_skip_optional()}
                                </Select.Item>
                              {/if}
                              {#each resolution.suggestions as candidate (getFlowPackageCandidateKey(candidate))}
                                <Select.Item
                                  value={getFlowPackageCandidateKey(candidate)}
                                  label={candidate.label}
                                >
                                  {candidate.label}
                                </Select.Item>
                              {/each}
                            </Select.Content>
                          </Select.Root>
                        {/if}
                      </div>
                    </li>
                  {/each}
                </ul>
              {/if}
            </section>
          {/if}

          {#if importError}
            <Alert.Root variant="destructive">
              <AlertTriangle class="size-4" />
              <Alert.Title>{m.error()}</Alert.Title>
              <Alert.Description>{importError}</Alert.Description>
            </Alert.Root>
          {/if}
        </div>
      {/if}
    </div>

    <div
      class="border-default bg-background flex flex-col-reverse gap-2 border-t px-5 py-3.5 sm:flex-row sm:justify-end sm:px-6"
    >
      <Button variant="outline" onclick={() => handleOpenChange(false)} disabled={importing}>
        {m.cancel()}
      </Button>
      <Button onclick={importPackage} disabled={!canSubmit}>
        {#if importing}
          <Loader2 class="size-4 animate-spin" />
          {m.flow_package_importing()}
        {:else}
          <Upload class="size-4" />
          {m.flow_package_import_as_draft()}
        {/if}
      </Button>
    </div>
  </Dialog.Content>
</Dialog.Root>
