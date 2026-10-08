<script lang="ts">
  import { untrack } from "svelte";
  import { formatRecordingLength } from "$lib/features/audio/recordingLimits";
  import { beforeNavigate } from "$app/navigation";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import { Page, Settings } from "$lib/components/layout";
  import {
    NumberField,
    SettingsForm,
    ToggleNumberField
  } from "$lib/components/layout/Settings/form.svelte";
  import { toast } from "$lib/components/toast";
  import { getEneo } from "$lib/core/Eneo";
  import { toastError } from "$lib/core/errors";
  import { FLOW_RETENTION_MAX_DAYS } from "$lib/features/flows/flowRunRetentionPolicy";
  import { m } from "$lib/paraglide/messages";
  import FlowRetentionAccessPanel from "./FlowRetentionAccessPanel.svelte";
  import type { FlowSettingsAdminData } from "./flowSettingsData";
  import {
    isRunCapacityExceededError,
    saveFlowAdminSettings,
    type FlowAdminSettingsUpdates
  } from "./flowSettingsAdminSave";

  let { data }: { data: FlowSettingsAdminData } = $props();
  const eneo = getEneo();

  // Fields deliberately capture the load snapshot (untracked on purpose);
  // commit() re-baselines them from server responses after each save.
  const initial = untrack(() => data);

  // Binary multiples: every byte figure on this page is labelled MiB / KiB,
  // matching what the deployment ceilings are actually expressed in.
  const MB = 1024 * 1024;
  const KB = 1024;
  // A size in MiB means nothing to an administrator choosing a limit for
  // meeting recordings, so the audio field states the running time it buys.
  // The assumed bitrate is stated in the copy, because a real recording's
  // running time depends on its own format and quality.
  const MP3_BYTES_PER_SECOND = 128_000 / 8;
  const EVIDENCE_MAX_SOURCES = 500;
  const EVIDENCE_MAX_PASSAGES = 50;
  const EVIDENCE_MAX_PASSAGE_BYTES = 65536;
  const EVIDENCE_MAX_STEP_BYTES = 4194304;

  let policy = $state(initial.flowRetentionPolicy);
  let runtimeLimitsOpen = $state(false);
  let saving = $state(false);
  let runRetentionDirty = $state(false);

  // --- Gallring ---
  const uploadCleanup = new ToggleNumberField({
    initial: initial.flowRetentionPolicy.flow_runtime_upload_abandonment_days,
    min: 1,
    max: FLOW_RETENTION_MAX_DAYS,
    suggestion: 30
  });

  // --- Uppladdningar & körning ---
  // Bounds mirror backend admission caps in flow_input_limits.py.
  const maxFilesPerRun = new NumberField({
    initial: initial.flowInputLimits.max_files_per_run,
    min: 1,
    max: 1000
  });
  const audioMaxFiles = new NumberField({
    initial: initial.flowInputLimits.audio_max_files_per_run,
    min: 1,
    max: 100
  });
  // Edited in minutes, stored in seconds; the deployment sets the ceiling.
  const audioMaxDuration = new NumberField({
    initial: initial.flowInputLimits.audio_max_duration_seconds,
    scale: 60,
    min: 60,
    max: initial.flowInputLimits.audio_max_duration_ceiling_seconds
  });
  const defaultStepTimeout = new NumberField({
    initial: initial.flowRuntimePolicy.default_step_timeout_seconds,
    min: 1,
    max: initial.flowRuntimePolicy.hard_ceiling_seconds
  });
  const maxStepTimeout = new NumberField({
    initial: initial.flowRuntimePolicy.max_step_timeout_seconds,
    min: 1,
    max: initial.flowRuntimePolicy.hard_ceiling_seconds
  });
  // Server capacity bounds the value; entering it restores the default (the
  // server stores no override), so the field always shows an effective number.
  const runCapacity = initial.flowRuntimePolicy.max_concurrent_runs_capacity;
  // The saved value, which stays stored when capacity limits it: the field shows
  // the effective number, so inherited and clamped need telling apart here.
  let runLimitOverride = $state(initial.flowRuntimePolicy.max_concurrent_runs_override ?? null);
  // Capacity 0 admits no run: the range message "between 0 and 0" would say
  // nothing, so the row states it instead and the field takes no new value.
  const maxConcurrentRuns = new NumberField({
    initial: initial.flowRuntimePolicy.max_concurrent_runs,
    min: runCapacity > 0 ? 1 : 0,
    max: runCapacity > 0 ? runCapacity : null,
    required: true
  });

  // --- AI Builder ---
  const builderMaxAttachments = new NumberField({
    initial: initial.aiBuilderBudgetSettings.max_attachments,
    min: 1,
    max: initial.aiBuilderBudgetSettings.max_attachments_hard_limit,
    required: true
  });
  const builderMaxMessageChars = new NumberField({
    initial: initial.aiBuilderBudgetSettings.max_message_chars,
    min: 1,
    max: initial.aiBuilderBudgetSettings.max_message_chars_hard_limit,
    required: true
  });
  // Off: the review model's own context window bounds the run evidence.
  const builderReviewEvidenceCap = new ToggleNumberField({
    initial: initial.aiBuilderBudgetSettings.review_evidence_max_input_tokens ?? null,
    min: 1,
    max: initial.aiBuilderBudgetSettings.budget_token_hard_limit,
    suggestion: 128_000
  });
  // The system bound caps the value; a tenant only lowers it, and entering the
  // bound itself restores inheritance (the server stores no override).
  const builderInvestigationEvidence = new NumberField({
    initial: initial.aiBuilderBudgetSettings.review_investigation_evidence_max_tokens,
    min: 1,
    max: initial.aiBuilderBudgetSettings.review_investigation_evidence_ceiling_tokens,
    required: true
  });
  const mappedCalls = new ToggleNumberField({
    initial: initial.mappedExecutionPolicy.max_provider_calls_per_mapped_step ?? null,
    min: 2,
    suggestion: 100
  });
  let mappedCallsSource = $state(initial.mappedExecutionPolicy.max_provider_calls_source);
  const mappedDeploymentDefault =
    initial.mappedExecutionPolicy.deployment_default_max_provider_calls ?? null;

  // --- Källunderlag ---
  const evidenceSources = new NumberField({
    initial: initial.ragEvidencePolicy.max_sources_with_recorded_passages,
    min: 1,
    max: EVIDENCE_MAX_SOURCES
  });
  const evidencePassages = new NumberField({
    initial: initial.ragEvidencePolicy.max_recorded_passages_per_source,
    min: 1,
    max: EVIDENCE_MAX_PASSAGES
  });
  const evidencePassageSize = new NumberField({
    initial: initial.ragEvidencePolicy.max_recorded_passage_bytes,
    scale: KB,
    min: KB,
    max: EVIDENCE_MAX_PASSAGE_BYTES
  });
  const evidenceStepSize = new NumberField({
    initial: initial.ragEvidencePolicy.max_recorded_passage_bytes_per_step,
    scale: KB,
    min: KB,
    max: EVIDENCE_MAX_STEP_BYTES
  });

  const form = new SettingsForm([
    uploadCleanup,
    maxFilesPerRun,
    audioMaxFiles,
    audioMaxDuration,
    defaultStepTimeout,
    maxStepTimeout,
    maxConcurrentRuns,
    builderMaxAttachments,
    builderMaxMessageChars,
    builderReviewEvidenceCap,
    builderInvestigationEvidence,
    mappedCalls,
    evidenceSources,
    evidencePassages,
    evidencePassageSize,
    evidenceStepSize
  ]);

  const retentionDirty = $derived(uploadCleanup.dirty);

  const timeoutOrderError = $derived(
    defaultStepTimeout.value != null &&
      maxStepTimeout.value != null &&
      defaultStepTimeout.value > maxStepTimeout.value
      ? m.flow_settings_error_timeout_order()
      : null
  );

  const blocked = $derived(
    form.invalid || timeoutOrderError !== null || (runCapacity === 0 && maxConcurrentRuns.dirty)
  );

  const uploadStatus = $derived.by(() => {
    const days = policy.flow_runtime_upload_abandonment_days;
    if (days == null) {
      return { active: false, label: m.flow_retention_status_no_upload_window() };
    }
    return { active: true, label: m.flow_retention_status_upload_eligible_days({ days }) };
  });

  // "45 s", "20 min" or "7 h 59 min": whole units, as the rest of the page says time.
  function formatSeconds(value: number): string {
    return value < 60 ? `${value} s` : formatRecordingLength(value * 1000);
  }

  function timeoutHint(field: NumberField): string {
    if (field.value == null || field.value === undefined) {
      return m.flow_runtime_policy_hard_ceiling_hint({
        value: formatSeconds(data.flowRuntimePolicy.hard_ceiling_seconds)
      });
    }
    return m.flow_runtime_policy_seconds_preview({ value: formatSeconds(field.value) });
  }

  const runtimeLimitsSummary = $derived(
    m.flow_runtime_policy_advanced_summary({
      normal: formatSeconds(
        defaultStepTimeout.value ?? initial.flowRuntimePolicy.hard_ceiling_seconds
      ),
      maximum: formatSeconds(maxStepTimeout.value ?? initial.flowRuntimePolicy.hard_ceiling_seconds)
    })
  );

  function formatStorage(value: number | null | undefined): string {
    if (value == null) return m.flow_knowledge_evidence_default_hint();
    if (value >= 1024 * MB) return `${Number((value / (1024 * MB)).toFixed(1))} GiB`;
    if (value >= MB) return `${Number((value / MB).toFixed(1))} MiB`;
    if (value >= KB) return `${Number((value / KB).toFixed(1))} KiB`;
    return `${value} B`;
  }

  /** Say what an audio size limit buys, in running time an admin recognises. */
  function audioRunningTime(bytes: number): string {
    const minutes = Math.round(bytes / MP3_BYTES_PER_SECOND / 60);
    if (minutes < 60) {
      return m.flow_input_limits_audio_equivalent_minutes({ minutes });
    }
    return m.flow_input_limits_audio_equivalent_hours({
      hours: Math.floor(minutes / 60),
      minutes: minutes % 60
    });
  }

  // The minutes as hours, as the value is typed, then the deployment's ceiling.
  const audioDurationHint = $derived.by(() => {
    const ceilingSeconds = initial.flowInputLimits.audio_max_duration_ceiling_seconds;
    const ceiling = m.flow_input_limits_ceiling_hint({
      ceiling: `${Math.floor(ceilingSeconds / 60)} min (${formatRecordingLength(ceilingSeconds * 1000)})`
    });
    const seconds = audioMaxDuration.value;
    if (seconds == null || seconds < 3600) return ceiling;
    const duration = formatRecordingLength(seconds * 1000);
    return [m.flow_input_limits_audio_duration_equivalent({ duration }), ceiling];
  });

  // `value` is undefined while an entry is invalid, and `?? 0` turned that into
  // a confident"Högst 0 källor" — a policy nobody set, stated mid-keystroke.
  const evidenceSummary = $derived.by(() => {
    const sources = evidenceSources.value;
    const passages = evidencePassages.value;
    const total = evidenceStepSize.value;
    if (sources === undefined || passages === undefined || total === undefined) {
      return m.flow_knowledge_evidence_summary_pending();
    }
    return m.flow_knowledge_evidence_summary({
      sources: sources ?? 0,
      passages: passages ?? 0,
      total: formatStorage(total)
    });
  });

  // One call is held back for a retry, so the budget buys one file fewer. Saying
  // that as"N calls cover N-1 files" left the arithmetic to the reader; with a
  // value entered, state the file count outright.
  const mappedCallsHint = $derived.by(() => {
    const calls = mappedCalls.value;
    if (calls == null || calls < 2) return m.flow_mapped_execution_calls_description();
    return m.flow_mapped_execution_calls_files_hint({ calls, files: calls - 1 });
  });

  const builderMessagePages = $derived(
    Math.max(1, Math.round((builderMaxMessageChars.value ?? 0) / 2500))
  );
  type Patches = {
    retention: boolean;
    rest: FlowAdminSettingsUpdates;
  };

  function collectPatches(): Patches | null {
    if (form.invalid) return null;

    const inputLimits: FlowAdminSettingsUpdates["inputLimits"] = {};
    if (maxFilesPerRun.dirty) inputLimits.max_files_per_run = maxFilesPerRun.value;
    if (audioMaxFiles.dirty) inputLimits.audio_max_files_per_run = audioMaxFiles.value;
    if (audioMaxDuration.dirty) inputLimits.audio_max_duration_seconds = audioMaxDuration.value;

    const runtimePolicy: FlowAdminSettingsUpdates["runtimePolicy"] = {};
    if (defaultStepTimeout.dirty) {
      runtimePolicy.default_step_timeout_seconds = defaultStepTimeout.value;
    }
    if (maxStepTimeout.dirty) runtimePolicy.max_step_timeout_seconds = maxStepTimeout.value;
    if (maxConcurrentRuns.dirty) runtimePolicy.max_concurrent_runs = maxConcurrentRuns.value;

    const mappedExecution: FlowAdminSettingsUpdates["mappedExecution"] = {};
    if (mappedCalls.dirty) {
      mappedExecution.max_provider_calls_per_mapped_step = mappedCalls.value;
    }

    const builderBudget: FlowAdminSettingsUpdates["builderBudget"] = {};
    if (builderMaxAttachments.dirty) {
      builderBudget.max_attachments = builderMaxAttachments.value ?? undefined;
    }
    if (builderMaxMessageChars.dirty) {
      builderBudget.max_message_chars = builderMaxMessageChars.value ?? undefined;
    }
    if (builderReviewEvidenceCap.dirty) {
      builderBudget.review_evidence_max_input_tokens = builderReviewEvidenceCap.value;
    }
    if (builderInvestigationEvidence.dirty) {
      builderBudget.review_investigation_evidence_max_tokens =
        builderInvestigationEvidence.value ?? undefined;
    }

    const ragEvidence: FlowAdminSettingsUpdates["ragEvidence"] = {};
    if (evidenceSources.dirty) {
      ragEvidence.max_sources_with_recorded_passages = evidenceSources.value;
    }
    if (evidencePassages.dirty) {
      ragEvidence.max_recorded_passages_per_source = evidencePassages.value;
    }
    if (evidencePassageSize.dirty) {
      ragEvidence.max_recorded_passage_bytes = evidencePassageSize.value;
    }
    if (evidenceStepSize.dirty) {
      ragEvidence.max_recorded_passage_bytes_per_step = evidenceStepSize.value;
    }

    return {
      retention: retentionDirty,
      rest: {
        inputLimits: Object.keys(inputLimits).length ? inputLimits : null,
        runtimePolicy: Object.keys(runtimePolicy).length ? runtimePolicy : null,
        mappedExecution: Object.keys(mappedExecution).length ? mappedExecution : null,
        builderBudget: Object.keys(builderBudget).length ? builderBudget : null,
        ragEvidence: Object.keys(ragEvidence).length ? ragEvidence : null
      }
    };
  }

  async function persist(patches: Patches) {
    if (patches.retention) {
      policy = await eneo.settings.updateFlowRetentionPolicy({
        flow_runtime_upload_abandonment_days: uploadCleanup.value ?? null
      });
      uploadCleanup.commit(policy.flow_runtime_upload_abandonment_days);
    }

    const updated = await saveFlowAdminSettings(eneo.settings, patches.rest);
    if (updated.inputLimits) {
      maxFilesPerRun.commit(updated.inputLimits.max_files_per_run);
      audioMaxFiles.commit(updated.inputLimits.audio_max_files_per_run);
      audioMaxDuration.commit(updated.inputLimits.audio_max_duration_seconds);
    }
    if (updated.runtimePolicy) {
      runLimitOverride = updated.runtimePolicy.max_concurrent_runs_override ?? null;
      defaultStepTimeout.commit(updated.runtimePolicy.default_step_timeout_seconds);
      maxStepTimeout.commit(updated.runtimePolicy.max_step_timeout_seconds);
      maxConcurrentRuns.commit(updated.runtimePolicy.max_concurrent_runs);
    }
    if (updated.mappedExecution) {
      mappedCalls.commit(updated.mappedExecution.max_provider_calls_per_mapped_step ?? null);
      mappedCallsSource = updated.mappedExecution.max_provider_calls_source;
    }
    if (updated.builderBudget) {
      builderMaxAttachments.commit(updated.builderBudget.max_attachments);
      builderMaxMessageChars.commit(updated.builderBudget.max_message_chars);
      builderReviewEvidenceCap.commit(
        updated.builderBudget.review_evidence_max_input_tokens ?? null
      );
      builderInvestigationEvidence.commit(
        updated.builderBudget.review_investigation_evidence_max_tokens
      );
    }
    if (updated.ragEvidence) {
      evidenceSources.commit(updated.ragEvidence.max_sources_with_recorded_passages);
      evidencePassages.commit(updated.ragEvidence.max_recorded_passages_per_source);
      evidencePassageSize.commit(updated.ragEvidence.max_recorded_passage_bytes);
      evidenceStepSize.commit(updated.ragEvidence.max_recorded_passage_bytes_per_step);
    }

    toast.success(m.saved_successfully());
  }

  async function save() {
    if (saving || blocked || form.dirtyCount === 0) return;
    const patches = collectPatches();
    if (!patches) return;
    saving = true;
    try {
      await persist(patches);
    } catch (error) {
      if (isRunCapacityExceededError(error)) toast.error(m.flow_run_limit_exceeds_capacity_error());
      else toastError(error);
    } finally {
      saving = false;
    }
  }

  // Sends null whatever the field shows: a clamped saved value looks equal to
  // the capacity, so the field is never dirty for it.
  async function useServerCapacity() {
    if (saving) return;
    saving = true;
    try {
      const updated = await eneo.settings.updateFlowRuntimePolicy({ max_concurrent_runs: null });
      maxConcurrentRuns.commit(updated.max_concurrent_runs);
      runLimitOverride = updated.max_concurrent_runs_override ?? null;
      toast.success(m.saved_successfully());
    } catch (error) {
      toastError(error);
    } finally {
      saving = false;
    }
  }

  async function restoreMappedDefault() {
    if (saving) return;
    saving = true;
    try {
      const updated = await eneo.settings.updateMappedExecutionPolicy({
        restore_max_provider_calls_default: true
      });
      mappedCalls.commit(updated.max_provider_calls_per_mapped_step ?? null);
      mappedCallsSource = updated.max_provider_calls_source;
      toast.success(m.saved_successfully());
    } catch (error) {
      toastError(error);
    } finally {
      saving = false;
    }
  }

  function setRuntimeLimitsOpen(open: boolean) {
    if (!open && (defaultStepTimeout.dirty || maxStepTimeout.dirty || timeoutOrderError)) return;
    runtimeLimitsOpen = open;
  }

  $effect(() => {
    if (defaultStepTimeout.dirty || maxStepTimeout.dirty || timeoutOrderError) {
      runtimeLimitsOpen = true;
    }
  });

  beforeNavigate((navigation) => {
    if (form.dirtyCount === 0 && !runRetentionDirty) return;
    if (!confirm(m.flow_settings_leave_confirm())) navigation.cancel();
  });
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.flow_settings_title()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.flow_settings_title()} />
    <Page.Tabbar>
      <Page.TabTrigger tab="retention">{m.flow_settings_tab_retention()}</Page.TabTrigger>
      <Page.TabTrigger tab="uploads">{m.flow_settings_tab_uploads()}</Page.TabTrigger>
      <Page.TabTrigger tab="builder">{m.flow_settings_tab_builder()}</Page.TabTrigger>
      <Page.TabTrigger tab="evidence">{m.flow_settings_tab_evidence()}</Page.TabTrigger>
    </Page.Tabbar>
  </Page.Header>
  <Page.Main>
    <!--
      The header subtitle is hidden below the wide container breakpoint and, above it,
      runs under the centred tab strip, so this standing context never reads reliably
      there. It belongs with the tab panels: it holds for all four of them.
    -->
    <p class="text-secondary mx-auto w-full max-w-[1180px] px-6 pt-4 text-sm lg:px-4">
      {m.flow_settings_page_description()}
      <Button
        variant="link"
        href="/admin/audit-logs?actions=tenant_settings_updated,flow_run_retention_policy_changed,flow_retention_hold_placed,flow_retention_hold_review_extended,flow_retention_hold_released"
        class="text-secondary hover:text-primary h-auto p-0 text-sm underline underline-offset-2"
      >
        {m.flow_settings_changes_are_logged()}
      </Button>
    </p>
    <Page.Tab id="retention">
      <FlowRetentionAccessPanel
        data={initial}
        onDirtyChange={(dirty) => (runRetentionDirty = dirty)}
      />
      <Settings.Page density="compact">
        <Settings.Group
          title={m.flow_retention_upload_group()}
          description={m.flow_retention_upload_group_description()}
          density="compact"
        >
          <div class="mx-4 flex flex-wrap items-center gap-2 lg:mx-0.5">
            <span class="text-secondary text-xs font-medium">
              {m.flow_retention_status_uploads()}
            </span>
            <Badge variant="secondary">
              {uploadStatus.label}
            </Badge>
            {#if retentionDirty}
              <span class="text-secondary text-xs">
                {m.flow_retention_status_unsaved_note()}
              </span>
            {/if}
          </div>
          <Settings.ToggleNumberRow
            title={m.flow_retention_upload_title()}
            description={m.flow_retention_upload_description()}
            toggleLabel={m.flow_retention_upload_window_enable()}
            valueLabel={m.flow_retention_eligibility_after_label()}
            unit={m.flow_retention_days_suffix()}
            offStatus={m.flow_retention_upload_window_off_status()}
            info={m.flow_retention_upload_anchor_description()}
            field={uploadCleanup}
          />
        </Settings.Group>
      </Settings.Page>
    </Page.Tab>

    <Page.Tab id="uploads">
      <Settings.Page density="compact">
        <Settings.Group
          title={m.flow_input_limits_file_group()}
          description={m.flow_input_limits_file_group_description()}
          density="compact"
        >
          <Settings.Row
            title={m.flow_input_limits_file_title()}
            description={m.flow_upload_limit_shared()}
          >
            <p class="text-sm">{formatStorage(data.flowInputLimits.file_max_size_bytes)}</p>
            <Button variant="link" href="/admin/storage" class="h-auto w-fit px-0 text-sm"
              >{m.flow_upload_limit_manage()}</Button
            >
          </Settings.Row>
          <Settings.NumberRow
            title={m.flow_input_limits_max_files_title()}
            description={m.flow_input_limits_max_files_description()}
            placeholder={m.flow_input_limits_unlimited_hint()}
            field={maxFilesPerRun}
          />
        </Settings.Group>

        <Settings.Group
          title={m.flow_input_limits_audio_group()}
          description={m.flow_input_limits_audio_group_description()}
          density="compact"
        >
          <Settings.Row
            title={m.flow_input_limits_audio_title()}
            description={m.flow_upload_limit_shared()}
          >
            <p class="text-sm">{formatStorage(data.flowInputLimits.audio_max_size_bytes)}</p>
            <p class="text-secondary text-xs">
              {audioRunningTime(data.flowInputLimits.audio_max_size_bytes)}
            </p>
            <Button variant="link" href="/admin/storage" class="h-auto w-fit px-0 text-sm"
              >{m.flow_upload_limit_manage()}</Button
            >
          </Settings.Row>
          <Settings.NumberRow
            title={m.flow_input_limits_audio_max_files_title()}
            description={m.flow_input_limits_audio_max_files_description()}
            placeholder={m.flow_input_limits_deployment_default_hint()}
            info={m.flow_input_limits_audio_max_files_info()}
            field={audioMaxFiles}
          />
          <Settings.NumberRow
            title={m.flow_input_limits_audio_duration_title()}
            description={m.flow_input_limits_audio_duration_description()}
            placeholder={m.flow_input_limits_deployment_default_hint()}
            unit="min"
            info={m.flow_input_limits_audio_duration_info()}
            hint={audioDurationHint}
            field={audioMaxDuration}
          />
        </Settings.Group>

        <Settings.Group
          title={m.flow_run_limit_group()}
          description={m.flow_run_limit_group_description()}
          density="compact"
        >
          <Settings.NumberRow
            title={m.flow_run_limit_title()}
            description={m.flow_run_limit_description()}
            hint={runCapacity === 0
              ? undefined
              : runLimitOverride !== null && runLimitOverride > runCapacity
                ? m.flow_run_limit_clamped_hint({
                    limit: String(runCapacity),
                    saved: String(runLimitOverride)
                  })
                : m.flow_run_limit_capacity_hint({ capacity: String(runCapacity) })}
            externalError={runCapacity === 0 ? m.flow_run_limit_no_capacity() : null}
            field={maxConcurrentRuns}
          />
          {#if runLimitOverride !== null}
            <div class="px-4 lg:px-0.5">
              <Button variant="outline" size="sm" disabled={saving} onclick={useServerCapacity}>
                {m.flow_run_limit_use_capacity()}
              </Button>
            </div>
          {/if}
        </Settings.Group>

        <Settings.Group
          title={m.flow_runtime_policy_group()}
          description={m.flow_runtime_policy_group_description()}
          density="compact"
        >
          <Collapsible.Root
            bind:open={() => runtimeLimitsOpen, setRuntimeLimitsOpen}
            class="px-4 lg:px-0.5"
          >
            <Collapsible.Trigger
              class="border-default hover:bg-hover-dimmer focus-visible:ring-ring flex w-full items-center justify-between gap-4 rounded-lg border px-4 py-3 text-left focus-visible:ring-2 focus-visible:outline-none"
            >
              <span class="min-w-0">
                <span class="text-primary block text-sm font-semibold">
                  {m.flow_runtime_policy_advanced_title()}
                </span>
                <span class="text-secondary mt-0.5 block text-xs leading-relaxed">
                  {runtimeLimitsSummary}
                </span>
              </span>
              <ChevronDown
                class="text-secondary size-4 shrink-0 motion-safe:transition-transform motion-safe:duration-(--duration-quick) motion-safe:ease-(--ease-smooth-out) {runtimeLimitsOpen
                  ? 'rotate-180'
                  : ''}"
                aria-hidden="true"
              />
            </Collapsible.Trigger>
            <Collapsible.Content class="collapsible-animate">
              <div class="flex flex-col gap-4 pt-4">
                <Settings.NumberRow
                  title={m.flow_runtime_policy_default_timeout_title()}
                  description={m.flow_runtime_policy_default_timeout_description()}
                  placeholder={m.flow_input_limits_deployment_default_hint()}
                  unit={m.flow_settings_unit_seconds()}
                  hint={timeoutHint(defaultStepTimeout)}
                  field={defaultStepTimeout}
                />
                <Settings.NumberRow
                  title={m.flow_runtime_policy_max_timeout_title()}
                  description={m.flow_runtime_policy_max_timeout_description()}
                  placeholder={m.flow_input_limits_deployment_default_hint()}
                  unit={m.flow_settings_unit_seconds()}
                  hint={timeoutHint(maxStepTimeout)}
                  externalError={timeoutOrderError}
                  field={maxStepTimeout}
                />
              </div>
            </Collapsible.Content>
          </Collapsible.Root>
        </Settings.Group>
      </Settings.Page>
    </Page.Tab>

    <Page.Tab id="builder">
      <Settings.Page density="compact">
        <Settings.Group
          title={m.ai_builder_limits_group()}
          description={m.ai_builder_limits_group_description()}
          density="compact"
        >
          <Settings.NumberRow
            title={m.ai_builder_limits_max_attachments_title()}
            description={m.ai_builder_limits_max_attachments_description()}
            info={m.ai_builder_limits_max_attachments_info()}
            hint={m.ai_builder_limits_ceiling_hint({
              value: String(data.aiBuilderBudgetSettings.max_attachments_hard_limit)
            })}
            field={builderMaxAttachments}
          />
          <Settings.NumberRow
            title={m.ai_builder_limits_max_message_chars_title()}
            description={m.ai_builder_limits_max_message_chars_description()}
            unit={m.flow_settings_unit_chars()}
            hint={m.ai_builder_limits_message_hint({
              ceiling: String(data.aiBuilderBudgetSettings.max_message_chars_hard_limit),
              pages: builderMessagePages
            })}
            field={builderMaxMessageChars}
          />
          <Settings.ToggleNumberRow
            title={m.ai_builder_limits_review_evidence_title()}
            description={m.ai_builder_limits_review_evidence_description()}
            toggleLabel={m.ai_builder_limits_review_evidence_label()}
            valueLabel={m.flow_settings_value_max_label()}
            unit={m.flow_settings_unit_tokens()}
            offStatus={m.ai_builder_limits_review_evidence_off_status()}
            info={m.ai_builder_limits_review_evidence_info()}
            hint={m.ai_builder_limits_ceiling_hint({
              value: String(data.aiBuilderBudgetSettings.budget_token_hard_limit)
            })}
            field={builderReviewEvidenceCap}
          />
          <Settings.NumberRow
            title={m.ai_builder_limits_investigation_evidence_title()}
            description={m.ai_builder_limits_investigation_evidence_description()}
            unit={m.flow_settings_unit_tokens()}
            info={m.ai_builder_limits_investigation_evidence_info()}
            hint={m.ai_builder_limits_ceiling_hint({
              value: String(
                data.aiBuilderBudgetSettings.review_investigation_evidence_ceiling_tokens
              )
            })}
            field={builderInvestigationEvidence}
          />
        </Settings.Group>

        <Settings.Group
          title={m.flow_mapped_execution_group()}
          description={m.flow_mapped_execution_group_description()}
          density="compact"
        >
          <Settings.ToggleNumberRow
            title={m.flow_mapped_execution_enable_title()}
            description={m.flow_mapped_execution_enable_description()}
            toggleLabel={m.flow_mapped_execution_enable_label()}
            valueLabel={m.flow_settings_value_max_label()}
            unit={m.flow_settings_unit_calls_per_step()}
            offStatus={m.flow_mapped_execution_off_status()}
            info={m.flow_mapped_execution_info()}
            hint={mappedCallsHint}
            field={mappedCalls}
          />
          <div class="flex flex-col gap-2 px-4 xl:ml-[40%] xl:px-1">
            {#if mappedCallsSource === "invalid"}
              <Alert.Root variant="destructive" class="max-w-xl">
                <TriangleAlert aria-hidden="true" />
                <Alert.Description>
                  {m.flow_mapped_execution_invalid_state()}
                </Alert.Description>
              </Alert.Root>
            {/if}
            {#if mappedCallsSource === "deployment_default"}
              {#if !mappedCalls.dirty}
                <p class="text-secondary text-xs">
                  {m.flow_mapped_execution_inherited_hint()}
                </p>
              {/if}
            {:else}
              <Button
                variant="link"
                class="text-accent-stronger w-fit px-0"
                onclick={restoreMappedDefault}
                disabled={saving}
              >
                {mappedDeploymentDefault != null
                  ? m.flow_mapped_execution_restore_default_value({
                      value: mappedDeploymentDefault
                    })
                  : m.flow_mapped_execution_restore_default()}
              </Button>
            {/if}
          </div>
        </Settings.Group>
      </Settings.Page>
    </Page.Tab>

    <Page.Tab id="evidence">
      <Settings.Page density="compact">
        <Settings.Group
          title={m.flow_knowledge_evidence_group()}
          description={m.flow_knowledge_evidence_intro()}
          density="compact"
        >
          <Settings.NumberRow
            title={m.flow_knowledge_evidence_sources_title()}
            description={m.flow_knowledge_evidence_sources_description()}
            placeholder={m.flow_knowledge_evidence_default_hint()}
            hint={m.flow_knowledge_evidence_ceiling_hint({
              ceiling: String(EVIDENCE_MAX_SOURCES)
            })}
            field={evidenceSources}
          />
          <Settings.NumberRow
            title={m.flow_knowledge_evidence_passages_per_source_title()}
            description={m.flow_knowledge_evidence_passages_per_source_description()}
            placeholder={m.flow_knowledge_evidence_default_hint()}
            hint={m.flow_knowledge_evidence_ceiling_hint({
              ceiling: String(EVIDENCE_MAX_PASSAGES)
            })}
            field={evidencePassages}
          />
          <Settings.NumberRow
            title={m.flow_knowledge_evidence_passage_bytes_title()}
            description={m.flow_knowledge_evidence_passage_bytes_description()}
            placeholder={m.flow_knowledge_evidence_default_hint()}
            unit="KiB"
            hint={m.flow_knowledge_evidence_ceiling_bytes_hint({
              ceiling: `${EVIDENCE_MAX_PASSAGE_BYTES / KB} KiB`
            })}
            field={evidencePassageSize}
          />
          <Settings.NumberRow
            title={m.flow_knowledge_evidence_step_bytes_title()}
            description={m.flow_knowledge_evidence_step_bytes_description()}
            placeholder={m.flow_knowledge_evidence_default_hint()}
            unit="KiB"
            hint={m.flow_knowledge_evidence_ceiling_bytes_hint({
              ceiling: `${EVIDENCE_MAX_STEP_BYTES / MB} MiB`
            })}
            field={evidenceStepSize}
          />
          <Card.Root size="sm" class="mx-4 w-auto lg:mx-0.5">
            <Card.Header>
              <Card.Title>{m.flow_knowledge_evidence_summary_title()}</Card.Title>
              <Card.Description class="leading-relaxed">{evidenceSummary}</Card.Description>
            </Card.Header>
          </Card.Root>
        </Settings.Group>
      </Settings.Page>
    </Page.Tab>
  </Page.Main>

  {#if form.dirtyCount > 0}
    <div class="bg-frosted-glass-primary border-default z-10 border-t backdrop-blur-md">
      <div class="mx-auto flex w-full max-w-[1180px] items-center justify-between gap-4 px-4 py-3">
        <div class="min-w-0" aria-live="polite">
          <p class="text-secondary text-sm">
            {form.dirtyCount === 1
              ? m.flow_settings_unsaved_one()
              : m.flow_settings_unsaved_many({ count: form.dirtyCount })}
          </p>
          {#if timeoutOrderError}
            <p class="text-negative-stronger mt-0.5 text-xs">{timeoutOrderError}</p>
          {/if}
        </div>
        <div class="flex items-center gap-2">
          <Button variant="ghost" onclick={() => form.resetAll()} disabled={saving}>
            {m.discard_changes()}
          </Button>
          <Button onclick={save} disabled={blocked || saving}>
            {saving ? m.saving() : m.flow_settings_save_changes()}
          </Button>
        </div>
      </div>
    </div>
  {/if}
</Page.Root>
