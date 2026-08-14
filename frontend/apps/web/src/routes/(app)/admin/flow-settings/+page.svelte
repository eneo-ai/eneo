<script lang="ts">
  import { untrack } from "svelte";
  import type { FlowRetentionImpactPreview, FlowRetentionPolicy } from "@eneo/eneo-js";
  import { beforeNavigate } from "$app/navigation";
  import { resolve } from "$app/paths";
  import ChevronDown from "lucide-svelte/icons/chevron-down";
  import TriangleAlert from "lucide-svelte/icons/triangle-alert";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import { Page, Settings } from "$lib/components/layout";
  import {
    NumberField,
    SettingsForm,
    ToggleField,
    ToggleNumberField
  } from "$lib/components/layout/Settings/form.svelte";
  import { toast } from "$lib/components/toast";
  import { getEneo } from "$lib/core/Eneo";
  import { toastError } from "$lib/core/errors";
  import FlowRetentionImpactDialog from "$lib/features/flows/components/FlowRetentionImpactDialog.svelte";
  import FlowClassificationRetentionSettings from "$lib/features/flows/components/FlowClassificationRetentionSettings.svelte";
  import {
    confirmationFromFlowRetentionPreview,
    FLOW_RETENTION_MAX_DAYS,
    organizationRetentionChangeIsDestructive
  } from "$lib/features/flows/flowRetentionPolicy";
  import { m } from "$lib/paraglide/messages";
  import { saveFlowAdminSettings, type FlowAdminSettingsUpdates } from "./flowSettingsAdminSave";

  let { data } = $props();
  const eneo = getEneo();

  // Fields deliberately capture the load snapshot (untracked on purpose);
  // commit() re-baselines them from server responses after each save.
  const initial = untrack(() => data);

  const MB = 1024 * 1024;
  const KB = 1024;
  const EVIDENCE_MAX_SOURCES = 500;
  const EVIDENCE_MAX_PASSAGES = 50;
  const EVIDENCE_MAX_PASSAGE_BYTES = 65536;
  const EVIDENCE_MAX_STEP_BYTES = 4194304;

  let policy = $state<FlowRetentionPolicy>(initial.flowRetentionPolicy);
  let classificationDirtyCount = $state(0);
  let runtimeLimitsOpen = $state(false);
  let saving = $state(false);
  let preview = $state<FlowRetentionImpactPreview | null>(null);
  let previewOpen = $state(false);

  // --- Gallring ---
  const runHistory = new ToggleNumberField({
    initial: initial.flowRetentionPolicy.flow_run_history_retention_days,
    min: 1,
    max: FLOW_RETENTION_MAX_DAYS,
    suggestion: 365
  });
  const uploadCleanup = new ToggleNumberField({
    initial: initial.flowRetentionPolicy.flow_runtime_upload_abandonment_days,
    min: 1,
    max: FLOW_RETENTION_MAX_DAYS,
    suggestion: 30
  });
  const minimumRetention = new NumberField({
    initial: initial.flowRetentionPolicy.flow_run_history_minimum_retention_days,
    min: 1,
    max: FLOW_RETENTION_MAX_DAYS
  });
  const noPurge = new ToggleField(initial.flowRetentionPolicy.flow_run_history_no_purge);

  // --- Uppladdningar & körning ---
  const fileMaxSize = new NumberField({
    initial: initial.flowInputLimits.file_max_size_bytes,
    scale: MB,
    min: 1,
    max: initial.flowInputLimits.file_max_size_ceiling_bytes
  });
  // Bounds mirror backend admission caps in flow_input_limits.py.
  const maxFilesPerRun = new NumberField({
    initial: initial.flowInputLimits.max_files_per_run,
    min: 1,
    max: 1000
  });
  const audioMaxSize = new NumberField({
    initial: initial.flowInputLimits.audio_max_size_bytes,
    scale: MB,
    min: 1,
    max: initial.flowInputLimits.audio_max_size_ceiling_bytes
  });
  const audioMaxFiles = new NumberField({
    initial: initial.flowInputLimits.audio_max_files_per_run,
    min: 1,
    max: 100
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
    runHistory,
    uploadCleanup,
    minimumRetention,
    noPurge,
    fileMaxSize,
    maxFilesPerRun,
    audioMaxSize,
    audioMaxFiles,
    defaultStepTimeout,
    maxStepTimeout,
    builderMaxAttachments,
    builderMaxMessageChars,
    mappedCalls,
    evidenceSources,
    evidencePassages,
    evidencePassageSize,
    evidenceStepSize
  ]);

  const totalDirtyCount = $derived(form.dirtyCount + classificationDirtyCount);

  const retentionDirty = $derived(
    runHistory.dirty || uploadCleanup.dirty || minimumRetention.dirty || noPurge.dirty
  );

  const timeoutOrderError = $derived(
    defaultStepTimeout.value != null &&
      maxStepTimeout.value != null &&
      defaultStepTimeout.value > maxStepTimeout.value
      ? m.flow_settings_error_timeout_order()
      : null
  );

  const blocked = $derived(form.invalid || timeoutOrderError !== null);

  const runHistoryStatus = $derived.by(() => {
    if (!policy.effective_state.run_history_deletion_active) {
      return { active: false, label: m.flow_retention_status_not_deleting() };
    }
    const days = policy.flow_run_history_retention_days;
    return {
      active: true,
      label:
        days != null
          ? m.flow_retention_status_deleting_days({ days })
          : m.flow_retention_status_deleting_classification()
    };
  });

  const uploadStatus = $derived.by(() => {
    const days = policy.flow_runtime_upload_abandonment_days;
    if (!policy.effective_state.runtime_upload_abandonment_active || days == null) {
      return { active: false, label: m.flow_retention_status_not_cleaning() };
    }
    return { active: true, label: m.flow_retention_status_cleanup_days({ days }) };
  });

  const protectionStatus = $derived.by(() => {
    const paused = policy.effective_state.barrier_sources.some(
      (source) => source === "organization_no_purge" || source === "classification_no_purge"
    );
    if (paused) return m.flow_retention_status_protection_paused();
    if (policy.effective_state.barrier_sources.length > 0) {
      return m.flow_retention_status_protection_minimum();
    }
    return m.flow_retention_status_protection_none();
  });

  function formatSeconds(value: number): string {
    if (value < 60) return `${value} s`;
    const minutes = value / 60;
    if (minutes < 60) return `${Number.isInteger(minutes) ? minutes : minutes.toFixed(1)} min`;
    const hours = minutes / 60;
    return `${Number.isInteger(hours) ? hours : hours.toFixed(1)} h`;
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
    if (value >= MB) return `${Number((value / MB).toFixed(1))} MB`;
    return `${Number((value / KB).toFixed(1))} KB`;
  }

  const evidenceSummary = $derived(
    m.flow_knowledge_evidence_summary({
      sources: evidenceSources.value ?? 0,
      passages: evidencePassages.value ?? 0,
      total: formatStorage(evidenceStepSize.value)
    })
  );

  const builderMessagePages = $derived(
    Math.max(1, Math.round((builderMaxMessageChars.value ?? 0) / 2500))
  );

  function activationSourceLabel(
    source: FlowRetentionPolicy["effective_state"]["activation_sources"][number]
  ): string {
    return source === "organization"
      ? m.flow_retention_contributor_organization()
      : m.flow_retention_contributor_classification();
  }

  function barrierSourceLabel(
    source: FlowRetentionPolicy["effective_state"]["barrier_sources"][number]
  ): string {
    switch (source) {
      case "organization_minimum":
        return m.flow_retention_contributor_organization_minimum();
      case "classification_minimum":
        return m.flow_retention_contributor_classification_minimum();
      case "organization_no_purge":
        return m.flow_retention_source_organization_no_purge();
      case "classification_no_purge":
        return m.flow_retention_source_classification_no_purge();
    }
  }

  type Patches = {
    retention: boolean;
    rest: FlowAdminSettingsUpdates;
  };

  function collectPatches(): Patches | null {
    if (form.invalid) return null;

    const inputLimits: FlowAdminSettingsUpdates["inputLimits"] = {};
    if (fileMaxSize.dirty) inputLimits.file_max_size_bytes = fileMaxSize.value;
    if (audioMaxSize.dirty) inputLimits.audio_max_size_bytes = audioMaxSize.value;
    if (maxFilesPerRun.dirty) inputLimits.max_files_per_run = maxFilesPerRun.value;
    if (audioMaxFiles.dirty) inputLimits.audio_max_files_per_run = audioMaxFiles.value;

    const runtimePolicy: FlowAdminSettingsUpdates["runtimePolicy"] = {};
    if (defaultStepTimeout.dirty) {
      runtimePolicy.default_step_timeout_seconds = defaultStepTimeout.value;
    }
    if (maxStepTimeout.dirty) runtimePolicy.max_step_timeout_seconds = maxStepTimeout.value;

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

  async function persist(patches: Patches, confirmed: boolean) {
    if (patches.retention) {
      policy = await eneo.settings.updateFlowRetentionPolicy({
        flow_run_history_retention_days: runHistory.value ?? null,
        flow_run_history_minimum_retention_days: minimumRetention.value ?? null,
        flow_run_history_no_purge: noPurge.value,
        flow_runtime_upload_abandonment_days: uploadCleanup.value ?? null,
        ...(confirmed && preview
          ? { confirmation: confirmationFromFlowRetentionPreview(preview) }
          : {})
      });
      runHistory.commit(policy.flow_run_history_retention_days);
      uploadCleanup.commit(policy.flow_runtime_upload_abandonment_days);
      minimumRetention.commit(policy.flow_run_history_minimum_retention_days);
      noPurge.commit(policy.flow_run_history_no_purge);
    }

    const updated = await saveFlowAdminSettings(eneo.settings, patches.rest);
    if (updated.inputLimits) {
      fileMaxSize.commit(updated.inputLimits.file_max_size_bytes);
      audioMaxSize.commit(updated.inputLimits.audio_max_size_bytes);
      maxFilesPerRun.commit(updated.inputLimits.max_files_per_run);
      audioMaxFiles.commit(updated.inputLimits.audio_max_files_per_run);
    }
    if (updated.runtimePolicy) {
      defaultStepTimeout.commit(updated.runtimePolicy.default_step_timeout_seconds);
      maxStepTimeout.commit(updated.runtimePolicy.max_step_timeout_seconds);
    }
    if (updated.mappedExecution) {
      mappedCalls.commit(updated.mappedExecution.max_provider_calls_per_mapped_step ?? null);
      mappedCallsSource = updated.mappedExecution.max_provider_calls_source;
    }
    if (updated.builderBudget) {
      builderMaxAttachments.commit(updated.builderBudget.max_attachments);
      builderMaxMessageChars.commit(updated.builderBudget.max_message_chars);
    }
    if (updated.ragEvidence) {
      evidenceSources.commit(updated.ragEvidence.max_sources_with_recorded_passages);
      evidencePassages.commit(updated.ragEvidence.max_recorded_passages_per_source);
      evidencePassageSize.commit(updated.ragEvidence.max_recorded_passage_bytes);
      evidenceStepSize.commit(updated.ragEvidence.max_recorded_passage_bytes_per_step);
    }

    previewOpen = false;
    preview = null;
    toast.success(m.saved_successfully());
  }

  async function save() {
    if (saving || blocked || form.dirtyCount === 0) return;
    const patches = collectPatches();
    if (!patches) return;
    saving = true;
    try {
      if (
        patches.retention &&
        organizationRetentionChangeIsDestructive(
          policy,
          runHistory.value ?? null,
          uploadCleanup.value ?? null,
          minimumRetention.value ?? null,
          noPurge.value
        )
      ) {
        preview = await eneo.settings.previewFlowRetentionPolicy({
          flow_run_history_retention_days: runHistory.value ?? null,
          flow_run_history_minimum_retention_days: minimumRetention.value ?? null,
          flow_run_history_no_purge: noPurge.value,
          flow_runtime_upload_abandonment_days: uploadCleanup.value ?? null
        });
        previewOpen = true;
        return;
      }
      await persist(patches, false);
    } catch (error) {
      toastError(error);
    } finally {
      saving = false;
    }
  }

  async function confirmDestructiveChange() {
    if (saving || !preview) return;
    const patches = collectPatches();
    if (!patches) return;
    saving = true;
    try {
      await persist(patches, true);
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

  async function refreshEffectiveRetentionPolicy() {
    policy = await eneo.settings.getFlowRetentionPolicy();
  }

  function setClassificationDirtyCount(count: number) {
    classificationDirtyCount = count;
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
    if (totalDirtyCount === 0) return;
    if (!confirm(m.flow_settings_leave_confirm())) navigation.cancel();
  });
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.flow_settings_title()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.flow_settings_title()} description={m.flow_settings_page_description()} />
    <Page.Tabbar>
      <Page.TabTrigger tab="retention">{m.flow_settings_tab_retention()}</Page.TabTrigger>
      <Page.TabTrigger tab="uploads">{m.flow_settings_tab_uploads()}</Page.TabTrigger>
      <Page.TabTrigger tab="builder">{m.flow_settings_tab_builder()}</Page.TabTrigger>
      <Page.TabTrigger tab="evidence">{m.flow_settings_tab_evidence()}</Page.TabTrigger>
    </Page.Tabbar>
  </Page.Header>
  <Page.Main>
    <Page.Tab id="retention">
      <Settings.Page density="compact">
        <Settings.Group
          title={m.flow_retention_current_group()}
          description={m.flow_retention_current_description()}
          density="compact"
        >
          {#if retentionDirty}
            <Alert.Root class="mx-4 max-w-3xl lg:mx-0.5">
              <TriangleAlert aria-hidden="true" />
              <Alert.Description>{m.flow_retention_status_unsaved_note()}</Alert.Description>
            </Alert.Root>
          {/if}
          <Card.Root size="sm" class="mx-4 gap-0 py-0 lg:mx-0.5">
            <Card.Content class="grid p-0 sm:grid-cols-3">
              <div class="border-default flex min-w-0 flex-col gap-2 p-4 sm:border-r">
                <span class="text-secondary text-xs font-medium">
                  {m.flow_retention_status_run_history()}
                </span>
                <Badge variant={runHistoryStatus.active ? "default" : "secondary"}>
                  {runHistoryStatus.label}
                </Badge>
              </div>
              <div
                class="border-default flex min-w-0 flex-col gap-2 border-t p-4 sm:border-t-0 sm:border-r"
              >
                <span class="text-secondary text-xs font-medium">
                  {m.flow_retention_status_uploads()}
                </span>
                <Badge variant={uploadStatus.active ? "default" : "secondary"}>
                  {uploadStatus.label}
                </Badge>
              </div>
              <div class="border-default flex min-w-0 flex-col gap-2 border-t p-4 sm:border-t-0">
                <span class="text-secondary text-xs font-medium">
                  {m.flow_retention_status_protection()}
                </span>
                <Badge variant="outline">{protectionStatus}</Badge>
              </div>
            </Card.Content>
            {#if policy.effective_state.activation_sources.length > 0 || policy.effective_state.barrier_sources.length > 0 || policy.effective_state.classification_policy_count > 0}
              <Card.Content
                class="text-secondary border-default flex flex-wrap gap-x-6 gap-y-1 border-t py-3 text-xs"
              >
                {#if policy.effective_state.activation_sources.length > 0}
                  <p>
                    <span class="text-primary font-medium"
                      >{m.flow_retention_activation_sources()}:</span
                    >
                    {policy.effective_state.activation_sources
                      .map(activationSourceLabel)
                      .join(", ")}
                  </p>
                {/if}
                {#if policy.effective_state.barrier_sources.length > 0}
                  <p>
                    <span class="text-primary font-medium"
                      >{m.flow_retention_barrier_sources()}:</span
                    >
                    {policy.effective_state.barrier_sources.map(barrierSourceLabel).join(", ")}
                  </p>
                {/if}
                {#if policy.effective_state.classification_policy_count > 0}
                  <p>
                    {policy.effective_state.classification_policy_count === 1
                      ? m.flow_retention_classification_policy_count_one()
                      : m.flow_retention_classification_policy_count({
                          count: policy.effective_state.classification_policy_count
                        })}
                  </p>
                {/if}
              </Card.Content>
            {/if}
          </Card.Root>
        </Settings.Group>

        <Settings.Group
          title={m.flow_retention_group_automatic()}
          description={m.flow_retention_group_automatic_description()}
          density="compact"
        >
          <Settings.ToggleNumberRow
            title={m.flow_retention_run_history_title()}
            description={m.flow_retention_run_history_description()}
            toggleLabel={m.flow_retention_run_history_enable()}
            valueLabel={m.flow_retention_delete_after_label()}
            unit={m.flow_retention_days_suffix()}
            offStatus={m.flow_retention_run_history_off_status()}
            info={m.flow_retention_run_history_info()}
            field={runHistory}
          />
          <Settings.ToggleNumberRow
            title={m.flow_retention_upload_title()}
            description={m.flow_retention_upload_description()}
            toggleLabel={m.flow_retention_upload_enable()}
            valueLabel={m.flow_retention_cleanup_after_label()}
            unit={m.flow_retention_days_suffix()}
            offStatus={m.flow_retention_upload_off_status()}
            info={m.flow_retention_upload_anchor_description()}
            field={uploadCleanup}
          />
        </Settings.Group>

        <Settings.Group
          title={m.flow_retention_group_preservation()}
          description={m.flow_retention_group_preservation_description()}
          density="compact"
        >
          <Settings.NumberRow
            title={m.flow_retention_minimum_title()}
            description={m.flow_retention_minimum_description()}
            placeholder={m.flow_retention_no_minimum()}
            unit={m.flow_retention_days_suffix()}
            info={m.flow_retention_minimum_info()}
            field={minimumRetention}
          />
          <Settings.ToggleRow
            title={m.flow_retention_no_purge_title()}
            description={m.flow_retention_no_purge_description()}
            label={m.flow_retention_no_purge_checkbox()}
            field={noPurge}
          />
          {#if noPurge.value}
            <Alert.Root class="mx-4 max-w-3xl lg:mx-0.5">
              <TriangleAlert aria-hidden="true" />
              <Alert.Description>{m.flow_retention_no_purge_warning()}</Alert.Description>
            </Alert.Root>
          {/if}
        </Settings.Group>

        <Settings.Group
          title={m.flow_retention_group_classifications()}
          description={m.flow_retention_group_classifications_description()}
          density="compact"
        >
          <FlowClassificationRetentionSettings
            initialPolicies={initial.flowClassificationRetentionPolicies}
            classifications={initial.securityClassifications.security_classifications}
            securityEnabled={initial.securityClassifications.security_enabled}
            onDirtyCountChange={setClassificationDirtyCount}
            onPoliciesChanged={refreshEffectiveRetentionPolicy}
          />
        </Settings.Group>

        <Settings.Group
          title={m.flow_retention_effective_group()}
          description={m.flow_retention_effective_group_description()}
          density="compact"
        >
          <div class="grid gap-3 px-4 lg:grid-cols-2 lg:px-0.5">
            <Card.Root size="sm">
              <Card.Header>
                <Card.Title>{m.flow_retention_audit_title()}</Card.Title>
                <Card.Description class="leading-relaxed">
                  {m.flow_retention_audit_description()}
                </Card.Description>
              </Card.Header>
              <Card.Content>
                <Button
                  variant="link"
                  class="h-auto px-0"
                  href={resolve("/(app)/admin/audit-logs")}
                >
                  {m.flow_retention_audit_link()}
                </Button>
              </Card.Content>
            </Card.Root>
            <Card.Root size="sm">
              <Card.Header>
                <Card.Title>{m.flow_retention_preservation_title()}</Card.Title>
                <Card.Description class="leading-relaxed">
                  {m.flow_retention_preservation_hold_caveat()}
                </Card.Description>
              </Card.Header>
            </Card.Root>
          </div>
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
          <Settings.NumberRow
            title={m.flow_input_limits_file_title()}
            description={m.flow_input_limits_file_description()}
            placeholder={m.flow_input_limits_deployment_default_hint()}
            unit="MB"
            hint={m.flow_knowledge_evidence_ceiling_bytes_hint({
              ceiling: `${Math.floor(initial.flowInputLimits.file_max_size_ceiling_bytes / MB)} MB`
            })}
            field={fileMaxSize}
          />
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
          <Settings.NumberRow
            title={m.flow_input_limits_audio_title()}
            description={m.flow_input_limits_audio_description()}
            placeholder={m.flow_input_limits_deployment_default_hint()}
            unit="MB"
            hint={m.flow_knowledge_evidence_ceiling_bytes_hint({
              ceiling: `${Math.floor(initial.flowInputLimits.audio_max_size_ceiling_bytes / MB)} MB`
            })}
            field={audioMaxSize}
          />
          <Settings.NumberRow
            title={m.flow_input_limits_audio_max_files_title()}
            description={m.flow_input_limits_audio_max_files_description()}
            placeholder={m.flow_input_limits_deployment_default_hint()}
            field={audioMaxFiles}
          />
        </Settings.Group>

        <Settings.Group
          title={m.flow_runtime_policy_group()}
          description={m.flow_runtime_policy_group_description()}
          density="compact"
        >
          <Collapsible.Root
            open={runtimeLimitsOpen}
            onOpenChange={setRuntimeLimitsOpen}
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
                class={runtimeLimitsOpen
                  ? "size-4 shrink-0 rotate-180 transition-transform duration-150 motion-reduce:transition-none"
                  : "size-4 shrink-0 transition-transform duration-150 motion-reduce:transition-none"}
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
            hint={m.flow_mapped_execution_calls_description()}
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
                class="w-fit px-0"
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
            unit="KB"
            hint={m.flow_knowledge_evidence_ceiling_bytes_hint({
              ceiling: `${EVIDENCE_MAX_PASSAGE_BYTES / KB} KB`
            })}
            field={evidencePassageSize}
          />
          <Settings.NumberRow
            title={m.flow_knowledge_evidence_step_bytes_title()}
            description={m.flow_knowledge_evidence_step_bytes_description()}
            placeholder={m.flow_knowledge_evidence_default_hint()}
            unit="KB"
            hint={m.flow_knowledge_evidence_ceiling_bytes_hint({
              ceiling: `${EVIDENCE_MAX_STEP_BYTES / MB} MB`
            })}
            field={evidenceStepSize}
          />
          <Card.Root size="sm" class="mx-4 lg:mx-0.5">
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
            <p class="text-negative-default mt-0.5 text-xs">{timeoutOrderError}</p>
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

{#if preview}
  <FlowRetentionImpactDialog
    bind:open={previewOpen}
    {preview}
    confirming={saving}
    onConfirm={confirmDestructiveChange}
  />
{/if}
