<script lang="ts">
  import { Page, Settings } from "$lib/components/layout";
  import { Button } from "@eneo/ui";
  import { toast } from "$lib/components/toast";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";
  import { resolve } from "$app/paths";
  import type {
    AIBuilderBudgetSettingsUpdate,
    FlowInputLimitsUpdate,
    FlowMappedExecutionPolicyUpdate,
    FlowRuntimePolicyUpdate
  } from "@eneo/eneo-js";
  import { saveFlowAdminSettings } from "./flowSettingsAdminSave";

  let { data } = $props();
  const eneo = getEneo();

  let fileMaxSizeBytes = $state("");
  let audioMaxSizeBytes = $state("");
  let maxFilesPerRun = $state("");
  let audioMaxFilesPerRun = $state("");
  let defaultStepTimeoutSeconds = $state("");
  let maxStepTimeoutSeconds = $state("");
  let maxMappedProviderCalls = $state("");
  let maxMappedInputTokens = $state("");
  let builderMaxAttachments = $state("");
  let builderMaxMessageChars = $state("");
  let builderMaxTemplateBytes = $state("");
  let builderMaxTemplatePlaceholders = $state("");
  let builderSafetyBufferTokens = $state("");
  let builderMinimumConversationTokens = $state("");
  let isSaving = $state(false);

  let initialFileMaxSizeBytes = "";
  let initialAudioMaxSizeBytes = "";
  let initialMaxFilesPerRun = "";
  let initialAudioMaxFilesPerRun = "";
  let initialDefaultStepTimeoutSeconds = "";
  let initialMaxStepTimeoutSeconds = "";
  let initialMaxMappedProviderCalls = "";
  let initialMaxMappedInputTokens = "";
  let initialBuilderMaxAttachments = "";
  let initialBuilderMaxMessageChars = "";
  let initialBuilderMaxTemplateBytes = "";
  let initialBuilderMaxTemplatePlaceholders = "";
  let initialBuilderSafetyBufferTokens = "";
  let initialBuilderMinimumConversationTokens = "";

  $effect.pre(() => {
    const nextFileMaxSizeBytes = String(data.flowInputLimits.file_max_size_bytes ?? "");
    const nextAudioMaxSizeBytes = String(data.flowInputLimits.audio_max_size_bytes ?? "");
    const nextMaxFilesPerRun =
      data.flowInputLimits.max_files_per_run != null
        ? String(data.flowInputLimits.max_files_per_run)
        : "";
    const nextAudioMaxFilesPerRun =
      data.flowInputLimits.audio_max_files_per_run != null
        ? String(data.flowInputLimits.audio_max_files_per_run)
        : "";
    const nextDefaultStepTimeoutSeconds = String(
      data.flowRuntimePolicy.default_step_timeout_seconds ?? ""
    );
    const nextMaxStepTimeoutSeconds = String(data.flowRuntimePolicy.max_step_timeout_seconds ?? "");
    const nextMaxMappedProviderCalls = String(
      data.mappedExecutionPolicy.max_provider_calls_per_mapped_step ?? ""
    );
    const nextMaxMappedInputTokens = String(
      data.mappedExecutionPolicy.max_estimated_input_tokens_per_mapped_step ?? ""
    );
    const nextBuilderMaxAttachments = String(data.aiBuilderBudgetSettings.max_attachments);
    const nextBuilderMaxMessageChars = String(data.aiBuilderBudgetSettings.max_message_chars);
    const nextBuilderMaxTemplateBytes = String(
      data.aiBuilderBudgetSettings.max_template_inspection_uncompressed_bytes
    );
    const nextBuilderMaxTemplatePlaceholders = String(
      data.aiBuilderBudgetSettings.max_template_placeholders
    );
    const nextBuilderSafetyBufferTokens = String(
      data.aiBuilderBudgetSettings.conversation_safety_buffer_tokens
    );
    const nextBuilderMinimumConversationTokens = String(
      data.aiBuilderBudgetSettings.minimum_conversation_budget_tokens
    );

    fileMaxSizeBytes = nextFileMaxSizeBytes;
    audioMaxSizeBytes = nextAudioMaxSizeBytes;
    maxFilesPerRun = nextMaxFilesPerRun;
    audioMaxFilesPerRun = nextAudioMaxFilesPerRun;
    defaultStepTimeoutSeconds = nextDefaultStepTimeoutSeconds;
    maxStepTimeoutSeconds = nextMaxStepTimeoutSeconds;
    maxMappedProviderCalls = nextMaxMappedProviderCalls;
    maxMappedInputTokens = nextMaxMappedInputTokens;
    builderMaxAttachments = nextBuilderMaxAttachments;
    builderMaxMessageChars = nextBuilderMaxMessageChars;
    builderMaxTemplateBytes = nextBuilderMaxTemplateBytes;
    builderMaxTemplatePlaceholders = nextBuilderMaxTemplatePlaceholders;
    builderSafetyBufferTokens = nextBuilderSafetyBufferTokens;
    builderMinimumConversationTokens = nextBuilderMinimumConversationTokens;

    initialFileMaxSizeBytes = nextFileMaxSizeBytes;
    initialAudioMaxSizeBytes = nextAudioMaxSizeBytes;
    initialMaxFilesPerRun = nextMaxFilesPerRun;
    initialAudioMaxFilesPerRun = nextAudioMaxFilesPerRun;
    initialDefaultStepTimeoutSeconds = nextDefaultStepTimeoutSeconds;
    initialMaxStepTimeoutSeconds = nextMaxStepTimeoutSeconds;
    initialMaxMappedProviderCalls = nextMaxMappedProviderCalls;
    initialMaxMappedInputTokens = nextMaxMappedInputTokens;
    initialBuilderMaxAttachments = nextBuilderMaxAttachments;
    initialBuilderMaxMessageChars = nextBuilderMaxMessageChars;
    initialBuilderMaxTemplateBytes = nextBuilderMaxTemplateBytes;
    initialBuilderMaxTemplatePlaceholders = nextBuilderMaxTemplatePlaceholders;
    initialBuilderSafetyBufferTokens = nextBuilderSafetyBufferTokens;
    initialBuilderMinimumConversationTokens = nextBuilderMinimumConversationTokens;
  });

  function normalizeNumericInput(value: unknown): string {
    return value == null ? "" : String(value).trim();
  }

  function toPositiveInteger(value: unknown, label: string): number {
    const normalizedValue = normalizeNumericInput(value);
    const parsed = Number(normalizedValue);
    if (!Number.isFinite(parsed) || parsed <= 0 || !Number.isInteger(parsed)) {
      throw new Error(`${label} must be a positive integer.`);
    }
    return parsed;
  }

  function toPositiveIntegerOrNull(value: unknown, label: string): number | null {
    return normalizeNumericInput(value) === "" ? null : toPositiveInteger(value, label);
  }

  function formatBytes(bytes: number): string {
    if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    let value = bytes;
    let unitIndex = 0;
    while (value >= 1024 && unitIndex < units.length - 1) {
      value /= 1024;
      unitIndex += 1;
    }
    return `${value.toFixed(value >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
  }

  function formatLimitPreview(value: unknown): string {
    const normalizedValue = normalizeNumericInput(value);
    return normalizedValue === ""
      ? m.flow_input_limits_deployment_default_hint()
      : formatBytes(Number(normalizedValue));
  }

  function formatSeconds(value: number): string {
    if (value < 60) return `${value}s`;
    const minutes = value / 60;
    if (minutes < 60) return `${Number.isInteger(minutes) ? minutes : minutes.toFixed(1)} min`;
    const hours = minutes / 60;
    return `${Number.isInteger(hours) ? hours : hours.toFixed(1)} h`;
  }

  function formatTimeoutPreview(value: unknown): string {
    const normalizedValue = normalizeNumericInput(value);
    return normalizedValue === ""
      ? m.flow_input_limits_deployment_default_hint()
      : formatSeconds(Number(normalizedValue));
  }

  function getReadableErrorMessage(error: unknown): string {
    if (
      error &&
      typeof error === "object" &&
      "getReadableMessage" in error &&
      typeof error.getReadableMessage === "function"
    ) {
      return error.getReadableMessage();
    }
    return String(error);
  }

  async function saveLimits() {
    isSaving = true;
    try {
      const inputLimitsPatch: FlowInputLimitsUpdate = {};
      const runtimePolicyPatch: FlowRuntimePolicyUpdate = {};
      const mappedExecutionPatch: FlowMappedExecutionPolicyUpdate = {};
      const builderSettingsPatch: AIBuilderBudgetSettingsUpdate = {};

      if (fileMaxSizeBytes !== initialFileMaxSizeBytes) {
        inputLimitsPatch.file_max_size_bytes = toPositiveIntegerOrNull(
          fileMaxSizeBytes,
          "File max size"
        );
      }
      if (audioMaxSizeBytes !== initialAudioMaxSizeBytes) {
        inputLimitsPatch.audio_max_size_bytes = toPositiveIntegerOrNull(
          audioMaxSizeBytes,
          "Audio max size"
        );
      }
      if (maxFilesPerRun !== initialMaxFilesPerRun) {
        inputLimitsPatch.max_files_per_run =
          normalizeNumericInput(maxFilesPerRun) === ""
            ? null
            : toPositiveInteger(maxFilesPerRun, m.flow_input_limits_max_files_title());
      }
      if (audioMaxFilesPerRun !== initialAudioMaxFilesPerRun) {
        inputLimitsPatch.audio_max_files_per_run =
          normalizeNumericInput(audioMaxFilesPerRun) === ""
            ? null
            : toPositiveInteger(audioMaxFilesPerRun, m.flow_input_limits_audio_max_files_title());
      }
      if (defaultStepTimeoutSeconds !== initialDefaultStepTimeoutSeconds) {
        runtimePolicyPatch.default_step_timeout_seconds = toPositiveIntegerOrNull(
          defaultStepTimeoutSeconds,
          m.flow_runtime_policy_default_timeout_title()
        );
      }
      if (maxStepTimeoutSeconds !== initialMaxStepTimeoutSeconds) {
        runtimePolicyPatch.max_step_timeout_seconds = toPositiveIntegerOrNull(
          maxStepTimeoutSeconds,
          m.flow_runtime_policy_max_timeout_title()
        );
      }
      if (maxMappedProviderCalls !== initialMaxMappedProviderCalls) {
        mappedExecutionPatch.max_provider_calls_per_mapped_step = toPositiveIntegerOrNull(
          maxMappedProviderCalls,
          m.flow_mapped_execution_calls_title()
        );
      }
      if (maxMappedInputTokens !== initialMaxMappedInputTokens) {
        mappedExecutionPatch.max_estimated_input_tokens_per_mapped_step = toPositiveIntegerOrNull(
          maxMappedInputTokens,
          m.flow_mapped_execution_tokens_title()
        );
      }
      if (builderMaxAttachments !== initialBuilderMaxAttachments) {
        builderSettingsPatch.max_attachments = toPositiveInteger(
          builderMaxAttachments,
          m.ai_builder_limits_max_attachments_title()
        );
      }
      if (builderMaxMessageChars !== initialBuilderMaxMessageChars) {
        builderSettingsPatch.max_message_chars = toPositiveInteger(
          builderMaxMessageChars,
          m.ai_builder_limits_max_message_chars_title()
        );
      }
      if (builderMaxTemplateBytes !== initialBuilderMaxTemplateBytes) {
        builderSettingsPatch.max_template_inspection_uncompressed_bytes = toPositiveInteger(
          builderMaxTemplateBytes,
          m.ai_builder_limits_template_bytes_title()
        );
      }
      if (builderMaxTemplatePlaceholders !== initialBuilderMaxTemplatePlaceholders) {
        builderSettingsPatch.max_template_placeholders = toPositiveInteger(
          builderMaxTemplatePlaceholders,
          m.ai_builder_limits_template_placeholders_title()
        );
      }
      if (builderSafetyBufferTokens !== initialBuilderSafetyBufferTokens) {
        builderSettingsPatch.conversation_safety_buffer_tokens = toPositiveInteger(
          builderSafetyBufferTokens,
          m.ai_builder_limits_safety_buffer_title()
        );
      }
      if (builderMinimumConversationTokens !== initialBuilderMinimumConversationTokens) {
        builderSettingsPatch.minimum_conversation_budget_tokens = toPositiveInteger(
          builderMinimumConversationTokens,
          m.ai_builder_limits_conversation_budget_title()
        );
      }
      const shouldUpdateInputLimits = Object.keys(inputLimitsPatch).length > 0;
      const shouldUpdateRuntimePolicy = Object.keys(runtimePolicyPatch).length > 0;
      const shouldUpdateMappedExecution = Object.keys(mappedExecutionPatch).length > 0;
      const shouldUpdateBuilderSettings = Object.keys(builderSettingsPatch).length > 0;

      if (
        !shouldUpdateInputLimits &&
        !shouldUpdateRuntimePolicy &&
        !shouldUpdateMappedExecution &&
        !shouldUpdateBuilderSettings
      ) {
        toast.success(m.saved_successfully());
        return;
      }

      const {
        inputLimits: updatedInputLimits,
        runtimePolicy: updatedRuntimePolicy,
        mappedExecution: updatedMappedExecution,
        builderBudget: updatedBuilderSettings
      } = await saveFlowAdminSettings(eneo.settings, {
        inputLimits: shouldUpdateInputLimits ? inputLimitsPatch : null,
        runtimePolicy: shouldUpdateRuntimePolicy ? runtimePolicyPatch : null,
        mappedExecution: shouldUpdateMappedExecution ? mappedExecutionPatch : null,
        builderBudget: shouldUpdateBuilderSettings ? builderSettingsPatch : null
      });

      if (updatedInputLimits) {
        fileMaxSizeBytes = String(updatedInputLimits.file_max_size_bytes);
        audioMaxSizeBytes = String(updatedInputLimits.audio_max_size_bytes);
        maxFilesPerRun =
          updatedInputLimits.max_files_per_run != null
            ? String(updatedInputLimits.max_files_per_run)
            : "";
        audioMaxFilesPerRun =
          updatedInputLimits.audio_max_files_per_run != null
            ? String(updatedInputLimits.audio_max_files_per_run)
            : "";
      }
      if (updatedRuntimePolicy) {
        defaultStepTimeoutSeconds = String(updatedRuntimePolicy.default_step_timeout_seconds);
        maxStepTimeoutSeconds = String(updatedRuntimePolicy.max_step_timeout_seconds);
      }
      if (updatedMappedExecution) {
        maxMappedProviderCalls = String(
          updatedMappedExecution.max_provider_calls_per_mapped_step ?? ""
        );
        maxMappedInputTokens = String(
          updatedMappedExecution.max_estimated_input_tokens_per_mapped_step ?? ""
        );
      }
      if (updatedBuilderSettings) {
        builderMaxAttachments = String(updatedBuilderSettings.max_attachments);
        builderMaxMessageChars = String(updatedBuilderSettings.max_message_chars);
        builderMaxTemplateBytes = String(
          updatedBuilderSettings.max_template_inspection_uncompressed_bytes
        );
        builderMaxTemplatePlaceholders = String(updatedBuilderSettings.max_template_placeholders);
        builderSafetyBufferTokens = String(
          updatedBuilderSettings.conversation_safety_buffer_tokens
        );
        builderMinimumConversationTokens = String(
          updatedBuilderSettings.minimum_conversation_budget_tokens
        );
      }

      initialFileMaxSizeBytes = fileMaxSizeBytes;
      initialAudioMaxSizeBytes = audioMaxSizeBytes;
      initialMaxFilesPerRun = maxFilesPerRun;
      initialAudioMaxFilesPerRun = audioMaxFilesPerRun;
      initialDefaultStepTimeoutSeconds = defaultStepTimeoutSeconds;
      initialMaxStepTimeoutSeconds = maxStepTimeoutSeconds;
      initialMaxMappedProviderCalls = maxMappedProviderCalls;
      initialMaxMappedInputTokens = maxMappedInputTokens;
      initialBuilderMaxAttachments = builderMaxAttachments;
      initialBuilderMaxMessageChars = builderMaxMessageChars;
      initialBuilderMaxTemplateBytes = builderMaxTemplateBytes;
      initialBuilderMaxTemplatePlaceholders = builderMaxTemplatePlaceholders;
      initialBuilderSafetyBufferTokens = builderSafetyBufferTokens;
      initialBuilderMinimumConversationTokens = builderMinimumConversationTokens;

      toast.success(m.saved_successfully());
    } catch (error) {
      toast.error(getReadableErrorMessage(error));
    } finally {
      isSaving = false;
    }
  }
</script>

<svelte:head>
  <title>Eneo.ai - {m.admin()} - {m.flow_input_limits_title()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <a
      href={resolve("/(app)/admin")}
      class="text-accent-default hover:text-accent-default/80 inline-flex items-center gap-1 text-sm font-medium"
    >
      <span aria-hidden="true">&larr;</span>
      <span>{m.flow_input_limits_back_to_organisation()}</span>
    </a>
    <Page.Title title={m.flow_input_limits_title()}></Page.Title>
  </Page.Header>
  <Page.Main>
    <Settings.Page>
      <Settings.Group title={m.flow_input_limits_file_group()}>
        <Settings.Row
          title={m.flow_input_limits_file_title()}
          description={m.flow_input_limits_file_description()}
        >
          <div class="flex w-full max-w-sm flex-col gap-1">
            <input
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
              type="number"
              min="1"
              placeholder={m.flow_input_limits_deployment_default_hint()}
              bind:value={fileMaxSizeBytes}
            />
            <p class="text-secondary text-xs">{formatLimitPreview(fileMaxSizeBytes)}</p>
          </div>
        </Settings.Row>
        <Settings.Row
          title={m.flow_input_limits_max_files_title()}
          description={m.flow_input_limits_max_files_description()}
        >
          <div class="flex w-full max-w-sm flex-col gap-1">
            <input
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
              type="number"
              min="1"
              placeholder={m.flow_input_limits_unlimited_hint()}
              bind:value={maxFilesPerRun}
            />
          </div>
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.flow_input_limits_audio_group()}>
        <Settings.Row
          title={m.flow_input_limits_audio_title()}
          description={m.flow_input_limits_audio_description()}
        >
          <div class="flex w-full max-w-sm flex-col gap-1">
            <input
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
              type="number"
              min="1"
              placeholder={m.flow_input_limits_deployment_default_hint()}
              bind:value={audioMaxSizeBytes}
            />
            <p class="text-secondary text-xs">{formatLimitPreview(audioMaxSizeBytes)}</p>
          </div>
        </Settings.Row>
        <Settings.Row
          title={m.flow_input_limits_audio_max_files_title()}
          description={m.flow_input_limits_audio_max_files_description()}
        >
          <div class="flex w-full max-w-sm flex-col gap-1">
            <input
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
              type="number"
              min="1"
              placeholder={m.flow_input_limits_deployment_default_hint()}
              bind:value={audioMaxFilesPerRun}
            />
          </div>
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.flow_runtime_policy_group()}>
        <Settings.Row
          title={m.flow_runtime_policy_default_timeout_title()}
          description={m.flow_runtime_policy_default_timeout_description()}
        >
          <div class="flex w-full max-w-sm flex-col gap-1">
            <input
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
              type="number"
              min="1"
              max={data.flowRuntimePolicy.hard_ceiling_seconds}
              placeholder={m.flow_input_limits_deployment_default_hint()}
              bind:value={defaultStepTimeoutSeconds}
            />
            <p class="text-secondary text-xs">
              {m.flow_runtime_policy_seconds_preview({
                value: formatTimeoutPreview(defaultStepTimeoutSeconds)
              })}
            </p>
          </div>
        </Settings.Row>
        <Settings.Row
          title={m.flow_runtime_policy_max_timeout_title()}
          description={m.flow_runtime_policy_max_timeout_description()}
        >
          <div class="flex w-full max-w-sm flex-col gap-1">
            <input
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
              type="number"
              min="1"
              max={data.flowRuntimePolicy.hard_ceiling_seconds}
              placeholder={m.flow_input_limits_deployment_default_hint()}
              bind:value={maxStepTimeoutSeconds}
            />
            <p class="text-secondary text-xs">
              {m.flow_runtime_policy_hard_ceiling_hint({
                value: formatSeconds(data.flowRuntimePolicy.hard_ceiling_seconds)
              })}
            </p>
          </div>
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.ai_builder_limits_group()}>
        <Settings.Row
          title={m.ai_builder_limits_max_attachments_title()}
          description={m.ai_builder_limits_max_attachments_description()}
        >
          <div class="flex w-full max-w-sm flex-col gap-1">
            <input
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
              type="number"
              min="1"
              max={data.aiBuilderBudgetSettings.max_attachments_hard_limit}
              bind:value={builderMaxAttachments}
            />
            <p class="text-secondary text-xs">
              {m.ai_builder_limits_ceiling_hint({
                value: String(data.aiBuilderBudgetSettings.max_attachments_hard_limit)
              })}
            </p>
          </div>
        </Settings.Row>
        <Settings.Row
          title={m.ai_builder_limits_max_message_chars_title()}
          description={m.ai_builder_limits_max_message_chars_description()}
        >
          <div class="flex w-full max-w-sm flex-col gap-1">
            <input
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
              type="number"
              min="1"
              max={data.aiBuilderBudgetSettings.max_message_chars_hard_limit}
              bind:value={builderMaxMessageChars}
            />
            <p class="text-secondary text-xs">
              {m.ai_builder_limits_ceiling_hint({
                value: String(data.aiBuilderBudgetSettings.max_message_chars_hard_limit)
              })}
            </p>
          </div>
        </Settings.Row>
        <Settings.Row
          title={m.ai_builder_limits_template_bytes_title()}
          description={m.ai_builder_limits_template_bytes_description()}
        >
          <div class="flex w-full max-w-sm flex-col gap-1">
            <input
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
              type="number"
              min="1"
              max={data.aiBuilderBudgetSettings
                .max_template_inspection_uncompressed_bytes_hard_limit}
              bind:value={builderMaxTemplateBytes}
            />
            <p class="text-secondary text-xs">
              {m.ai_builder_limits_ceiling_hint({
                value: formatBytes(
                  data.aiBuilderBudgetSettings.max_template_inspection_uncompressed_bytes_hard_limit
                )
              })}
            </p>
            <p class="text-secondary text-xs">
              {m.ai_builder_limits_template_file_ceiling_hint({
                maxBytes: formatBytes(
                  data.aiBuilderBudgetSettings.max_template_uncompressed_bytes_per_file_hard_limit
                ),
                maxEntries: String(
                  data.aiBuilderBudgetSettings.max_template_archive_entries_per_file_hard_limit
                )
              })}
            </p>
          </div>
        </Settings.Row>
        <Settings.Row
          title={m.ai_builder_limits_template_placeholders_title()}
          description={m.ai_builder_limits_template_placeholders_description()}
        >
          <div class="flex w-full max-w-sm flex-col gap-1">
            <input
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
              type="number"
              min="1"
              max={data.aiBuilderBudgetSettings.max_template_placeholders_hard_limit}
              bind:value={builderMaxTemplatePlaceholders}
            />
            <p class="text-secondary text-xs">
              {m.ai_builder_limits_ceiling_hint({
                value: String(data.aiBuilderBudgetSettings.max_template_placeholders_hard_limit)
              })}
            </p>
            <p class="text-secondary text-xs">
              {m.ai_builder_limits_planning_state_ceiling_hint({
                value: formatBytes(
                  data.aiBuilderBudgetSettings.max_planning_state_payload_bytes_hard_limit
                )
              })}
            </p>
          </div>
        </Settings.Row>
        <Settings.Row
          title={m.ai_builder_limits_safety_buffer_title()}
          description={m.ai_builder_limits_safety_buffer_description()}
        >
          <div class="flex w-full max-w-sm flex-col gap-1">
            <input
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
              type="number"
              min="1"
              max={data.aiBuilderBudgetSettings.budget_token_hard_limit}
              bind:value={builderSafetyBufferTokens}
            />
          </div>
        </Settings.Row>
        <Settings.Row
          title={m.ai_builder_limits_conversation_budget_title()}
          description={m.ai_builder_limits_conversation_budget_description()}
        >
          <div class="flex w-full max-w-sm flex-col gap-1">
            <input
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
              type="number"
              min="1"
              max={data.aiBuilderBudgetSettings.budget_token_hard_limit}
              bind:value={builderMinimumConversationTokens}
            />
          </div>
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.flow_mapped_execution_group()}>
        <Settings.Row
          title={m.flow_mapped_execution_calls_title()}
          description={m.flow_mapped_execution_calls_description()}
        >
          <div class="flex w-full max-w-sm flex-col gap-1">
            <input
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
              type="number"
              min="1"
              placeholder={m.flow_mapped_execution_unset_hint()}
              bind:value={maxMappedProviderCalls}
            />
          </div>
        </Settings.Row>
        <Settings.Row
          title={m.flow_mapped_execution_tokens_title()}
          description={m.flow_mapped_execution_tokens_description()}
        >
          <div class="flex w-full max-w-sm flex-col gap-1">
            <input
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
              type="number"
              min="1"
              placeholder={m.flow_mapped_execution_unset_hint()}
              bind:value={maxMappedInputTokens}
            />
          </div>
        </Settings.Row>
      </Settings.Group>

      <div class="flex justify-end">
        <Button variant="primary" onclick={saveLimits} disabled={isSaving}>
          {isSaving ? m.saving() : m.save()}
        </Button>
      </div>
    </Settings.Page>
  </Page.Main>
</Page.Root>
