<script lang="ts">
  import { Page, Settings } from "$lib/components/layout";
  import { Button } from "@intric/ui";
  import { toast } from "$lib/components/toast";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";

  let { data } = $props();
  const intric = getIntric();

  let fileMaxSizeBytes = $state(String(data.flowInputLimits.file_max_size_bytes ?? ""));
  let audioMaxSizeBytes = $state(String(data.flowInputLimits.audio_max_size_bytes ?? ""));
  let maxFilesPerRun = $state(data.flowInputLimits.max_files_per_run != null ? String(data.flowInputLimits.max_files_per_run) : "");
  let audioMaxFilesPerRun = $state(data.flowInputLimits.audio_max_files_per_run != null ? String(data.flowInputLimits.audio_max_files_per_run) : "");
  let isSaving = $state(false);

  // Track initial values to detect changes
  let initialFileMaxSizeBytes = fileMaxSizeBytes;
  let initialAudioMaxSizeBytes = audioMaxSizeBytes;
  let initialMaxFilesPerRun = maxFilesPerRun;
  let initialAudioMaxFilesPerRun = audioMaxFilesPerRun;

  function toPositiveInteger(value: string, label: string): number {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed <= 0 || !Number.isInteger(parsed)) {
      throw new Error(`${label} must be a positive integer.`);
    }
    return parsed;
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

  async function saveLimits() {
    isSaving = true;
    try {
      const patch: Record<string, number | null> = {};

      // Only include changed fields
      if (fileMaxSizeBytes !== initialFileMaxSizeBytes) {
        patch.file_max_size_bytes = toPositiveInteger(fileMaxSizeBytes, "File max size");
      }
      if (audioMaxSizeBytes !== initialAudioMaxSizeBytes) {
        patch.audio_max_size_bytes = toPositiveInteger(audioMaxSizeBytes, "Audio max size");
      }
      if (maxFilesPerRun !== initialMaxFilesPerRun) {
        patch.max_files_per_run = String(maxFilesPerRun).trim() === "" ? null : toPositiveInteger(String(maxFilesPerRun), m.flow_input_limits_max_files_title());
      }
      if (audioMaxFilesPerRun !== initialAudioMaxFilesPerRun) {
        patch.audio_max_files_per_run = String(audioMaxFilesPerRun).trim() === "" ? null : toPositiveInteger(String(audioMaxFilesPerRun), m.flow_input_limits_audio_max_files_title());
      }

      if (Object.keys(patch).length === 0) {
        toast.success(m.saved_successfully());
        return;
      }

      const updated = await intric.settings.updateFlowInputLimits(patch);
      fileMaxSizeBytes = String(updated.file_max_size_bytes);
      audioMaxSizeBytes = String(updated.audio_max_size_bytes);
      maxFilesPerRun = updated.max_files_per_run != null ? String(updated.max_files_per_run) : "";
      audioMaxFilesPerRun = updated.audio_max_files_per_run != null ? String(updated.audio_max_files_per_run) : "";

      // Update initial values after save
      initialFileMaxSizeBytes = fileMaxSizeBytes;
      initialAudioMaxSizeBytes = audioMaxSizeBytes;
      initialMaxFilesPerRun = maxFilesPerRun;
      initialAudioMaxFilesPerRun = audioMaxFilesPerRun;

      toast.success(m.saved_successfully());
    } catch (error) {
      const message = error?.getReadableMessage?.() ?? String(error);
      toast.error(message);
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
      href={localizeHref("/admin")}
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
        <Settings.Row title={m.flow_input_limits_file_title()} description={m.flow_input_limits_file_description()}>
          <div class="flex w-full max-w-sm flex-col gap-1">
            <input
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
              type="number"
              min="1"
              bind:value={fileMaxSizeBytes}
            />
            <p class="text-xs text-secondary">{formatBytes(Number(fileMaxSizeBytes))}</p>
          </div>
        </Settings.Row>
        <Settings.Row title={m.flow_input_limits_max_files_title()} description={m.flow_input_limits_max_files_description()}>
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
        <Settings.Row title={m.flow_input_limits_audio_title()} description={m.flow_input_limits_audio_description()}>
          <div class="flex w-full max-w-sm flex-col gap-1">
            <input
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
              type="number"
              min="1"
              bind:value={audioMaxSizeBytes}
            />
            <p class="text-xs text-secondary">{formatBytes(Number(audioMaxSizeBytes))}</p>
          </div>
        </Settings.Row>
        <Settings.Row title={m.flow_input_limits_audio_max_files_title()} description={m.flow_input_limits_audio_max_files_description()}>
          <div class="flex w-full max-w-sm flex-col gap-1">
            <input
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
              type="number"
              min="1"
              placeholder={m.flow_input_limits_default_hint({ value: "10" })}
              bind:value={audioMaxFilesPerRun}
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
