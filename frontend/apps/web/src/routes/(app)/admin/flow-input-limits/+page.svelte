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
  let isSaving = $state(false);

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
      const updated = await intric.settings.updateFlowInputLimits({
        file_max_size_bytes: toPositiveInteger(fileMaxSizeBytes, "File max size"),
        audio_max_size_bytes: toPositiveInteger(audioMaxSizeBytes, "Audio max size")
      });
      fileMaxSizeBytes = String(updated.file_max_size_bytes);
      audioMaxSizeBytes = String(updated.audio_max_size_bytes);
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
      <span aria-hidden="true"><-</span>
      <span>{m.flow_input_limits_back_to_organisation()}</span>
    </a>
    <Page.Title title={m.flow_input_limits_title()}></Page.Title>
  </Page.Header>
  <Page.Main>
    <Settings.Page>
      <Settings.Group title={m.flow_input_limits_group()}>
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
      </Settings.Group>

      <div class="flex justify-end">
        <Button variant="primary" onclick={saveLimits} disabled={isSaving}>
          {isSaving ? m.saving() : m.save()}
        </Button>
      </div>
    </Settings.Page>
  </Page.Main>
</Page.Root>
