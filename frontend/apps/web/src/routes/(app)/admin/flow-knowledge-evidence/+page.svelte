<script lang="ts">
  import { Page, Settings } from "$lib/components/layout";
  import { Button } from "@eneo/ui";
  import { toast } from "$lib/components/toast";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";
  import { resolve } from "$app/paths";

  let { data } = $props();
  const eneo = getEneo();

  // Ceilings an administrator cannot exceed. They are shown next to each field
  // so the bound is understood before a save is rejected, not after.
  const MAX_SOURCES_CEILING = 500;
  const MAX_PASSAGES_PER_SOURCE_CEILING = 50;
  const MAX_PASSAGE_BYTES_CEILING = 65536;
  const MAX_STEP_PASSAGE_BYTES_CEILING = 4194304;
  const MAX_RUN_VIEW_PASSAGE_BYTES_CEILING = 16777216;

  let maxSources = $state("");
  let maxPassagesPerSource = $state("");
  let maxPassageBytes = $state("");
  let maxStepPassageBytes = $state("");
  let maxRunViewPassageBytes = $state("");
  let isSaving = $state(false);

  let initialMaxSources = "";
  let initialMaxPassagesPerSource = "";
  let initialMaxPassageBytes = "";
  let initialMaxStepPassageBytes = "";
  let initialMaxRunViewPassageBytes = "";

  $effect.pre(() => {
    const policy = data.ragEvidencePolicy;
    const nextMaxSources = String(policy.max_sources_with_recorded_passages ?? "");
    const nextMaxPassagesPerSource = String(policy.max_recorded_passages_per_source ?? "");
    const nextMaxPassageBytes = String(policy.max_recorded_passage_bytes ?? "");
    const nextMaxStepPassageBytes = String(policy.max_recorded_passage_bytes_per_step ?? "");
    const nextMaxRunViewPassageBytes = String(policy.max_recorded_passage_bytes_per_run_view ?? "");

    maxSources = nextMaxSources;
    maxPassagesPerSource = nextMaxPassagesPerSource;
    maxPassageBytes = nextMaxPassageBytes;
    maxStepPassageBytes = nextMaxStepPassageBytes;
    maxRunViewPassageBytes = nextMaxRunViewPassageBytes;

    initialMaxSources = nextMaxSources;
    initialMaxPassagesPerSource = nextMaxPassagesPerSource;
    initialMaxPassageBytes = nextMaxPassageBytes;
    initialMaxStepPassageBytes = nextMaxStepPassageBytes;
    initialMaxRunViewPassageBytes = nextMaxRunViewPassageBytes;
  });

  function normalizeNumericInput(value: unknown): string {
    return value == null ? "" : String(value).trim();
  }

  function toBoundedInteger(value: unknown, label: string, ceiling: number): number {
    const normalizedValue = normalizeNumericInput(value);
    const parsed = Number(normalizedValue);
    if (!Number.isFinite(parsed) || parsed <= 0 || !Number.isInteger(parsed)) {
      throw new Error(m.flow_knowledge_evidence_error_positive_integer({ field: label }));
    }
    if (parsed > ceiling) {
      throw new Error(
        m.flow_knowledge_evidence_error_above_ceiling({
          field: label,
          ceiling: String(ceiling)
        })
      );
    }
    return parsed;
  }

  function toBoundedIntegerOrNull(value: unknown, label: string, ceiling: number): number | null {
    return normalizeNumericInput(value) === "" ? null : toBoundedInteger(value, label, ceiling);
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

  function formatBytePreview(value: unknown): string {
    const normalizedValue = normalizeNumericInput(value);
    return normalizedValue === ""
      ? m.flow_knowledge_evidence_default_hint()
      : formatBytes(Number(normalizedValue));
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
    if (error instanceof Error) {
      return error.message;
    }
    return String(error);
  }

  async function savePolicy() {
    isSaving = true;
    try {
      const patch: Record<string, number | null> = {};

      if (maxSources !== initialMaxSources) {
        patch.max_sources_with_recorded_passages = toBoundedIntegerOrNull(
          maxSources,
          m.flow_knowledge_evidence_sources_title(),
          MAX_SOURCES_CEILING
        );
      }
      if (maxPassagesPerSource !== initialMaxPassagesPerSource) {
        patch.max_recorded_passages_per_source = toBoundedIntegerOrNull(
          maxPassagesPerSource,
          m.flow_knowledge_evidence_passages_per_source_title(),
          MAX_PASSAGES_PER_SOURCE_CEILING
        );
      }
      if (maxPassageBytes !== initialMaxPassageBytes) {
        patch.max_recorded_passage_bytes = toBoundedIntegerOrNull(
          maxPassageBytes,
          m.flow_knowledge_evidence_passage_bytes_title(),
          MAX_PASSAGE_BYTES_CEILING
        );
      }
      if (maxStepPassageBytes !== initialMaxStepPassageBytes) {
        patch.max_recorded_passage_bytes_per_step = toBoundedIntegerOrNull(
          maxStepPassageBytes,
          m.flow_knowledge_evidence_step_bytes_title(),
          MAX_STEP_PASSAGE_BYTES_CEILING
        );
      }
      if (maxRunViewPassageBytes !== initialMaxRunViewPassageBytes) {
        patch.max_recorded_passage_bytes_per_run_view = toBoundedIntegerOrNull(
          maxRunViewPassageBytes,
          m.flow_knowledge_evidence_run_view_bytes_title(),
          MAX_RUN_VIEW_PASSAGE_BYTES_CEILING
        );
      }

      if (Object.keys(patch).length === 0) {
        toast.success(m.saved_successfully());
        return;
      }

      const updated = await eneo.settings.updateRagEvidencePolicy(patch);

      maxSources = String(updated.max_sources_with_recorded_passages);
      maxPassagesPerSource = String(updated.max_recorded_passages_per_source);
      maxPassageBytes = String(updated.max_recorded_passage_bytes);
      maxStepPassageBytes = String(updated.max_recorded_passage_bytes_per_step);
      maxRunViewPassageBytes = String(updated.max_recorded_passage_bytes_per_run_view);

      initialMaxSources = maxSources;
      initialMaxPassagesPerSource = maxPassagesPerSource;
      initialMaxPassageBytes = maxPassageBytes;
      initialMaxStepPassageBytes = maxStepPassageBytes;
      initialMaxRunViewPassageBytes = maxRunViewPassageBytes;

      toast.success(m.saved_successfully());
    } catch (error) {
      toast.error(getReadableErrorMessage(error));
    } finally {
      isSaving = false;
    }
  }
</script>

<svelte:head>
  <title>Eneo.ai - {m.admin()} - {m.flow_knowledge_evidence_title()}</title>
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
    <Page.Title title={m.flow_knowledge_evidence_title()}></Page.Title>
  </Page.Header>
  <Page.Main>
    <Settings.Page>
      <Settings.Group title={m.flow_knowledge_evidence_scope_group()}>
        <p class="text-secondary px-1 pb-2 text-sm">
          {m.flow_knowledge_evidence_intro()}
        </p>
        <Settings.Row
          title={m.flow_knowledge_evidence_sources_title()}
          description={m.flow_knowledge_evidence_sources_description()}
        >
          <div class="flex w-full max-w-sm flex-col gap-1">
            <input
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
              type="number"
              min="1"
              max={MAX_SOURCES_CEILING}
              placeholder={m.flow_knowledge_evidence_default_hint()}
              aria-describedby="max-sources-ceiling"
              bind:value={maxSources}
            />
            <p id="max-sources-ceiling" class="text-secondary text-xs">
              {m.flow_knowledge_evidence_ceiling_hint({ ceiling: String(MAX_SOURCES_CEILING) })}
            </p>
          </div>
        </Settings.Row>
        <Settings.Row
          title={m.flow_knowledge_evidence_passages_per_source_title()}
          description={m.flow_knowledge_evidence_passages_per_source_description()}
        >
          <div class="flex w-full max-w-sm flex-col gap-1">
            <input
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
              type="number"
              min="1"
              max={MAX_PASSAGES_PER_SOURCE_CEILING}
              placeholder={m.flow_knowledge_evidence_default_hint()}
              aria-describedby="max-passages-ceiling"
              bind:value={maxPassagesPerSource}
            />
            <p id="max-passages-ceiling" class="text-secondary text-xs">
              {m.flow_knowledge_evidence_ceiling_hint({
                ceiling: String(MAX_PASSAGES_PER_SOURCE_CEILING)
              })}
            </p>
          </div>
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.flow_knowledge_evidence_size_group()}>
        <Settings.Row
          title={m.flow_knowledge_evidence_passage_bytes_title()}
          description={m.flow_knowledge_evidence_passage_bytes_description()}
        >
          <div class="flex w-full max-w-sm flex-col gap-1">
            <input
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
              type="number"
              min="1"
              max={MAX_PASSAGE_BYTES_CEILING}
              placeholder={m.flow_knowledge_evidence_default_hint()}
              aria-describedby="max-passage-bytes-ceiling"
              bind:value={maxPassageBytes}
            />
            <p class="text-secondary text-xs">{formatBytePreview(maxPassageBytes)}</p>
            <p id="max-passage-bytes-ceiling" class="text-secondary text-xs">
              {m.flow_knowledge_evidence_ceiling_bytes_hint({
                ceiling: formatBytes(MAX_PASSAGE_BYTES_CEILING)
              })}
            </p>
          </div>
        </Settings.Row>
        <Settings.Row
          title={m.flow_knowledge_evidence_step_bytes_title()}
          description={m.flow_knowledge_evidence_step_bytes_description()}
        >
          <div class="flex w-full max-w-sm flex-col gap-1">
            <input
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
              type="number"
              min="1"
              max={MAX_STEP_PASSAGE_BYTES_CEILING}
              placeholder={m.flow_knowledge_evidence_default_hint()}
              aria-describedby="max-step-bytes-ceiling"
              bind:value={maxStepPassageBytes}
            />
            <p class="text-secondary text-xs">{formatBytePreview(maxStepPassageBytes)}</p>
            <p id="max-step-bytes-ceiling" class="text-secondary text-xs">
              {m.flow_knowledge_evidence_ceiling_bytes_hint({
                ceiling: formatBytes(MAX_STEP_PASSAGE_BYTES_CEILING)
              })}
            </p>
          </div>
        </Settings.Row>
        <Settings.Row
          title={m.flow_knowledge_evidence_run_view_bytes_title()}
          description={m.flow_knowledge_evidence_run_view_bytes_description()}
        >
          <div class="flex w-full max-w-sm flex-col gap-1">
            <input
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
              type="number"
              min="1"
              max={MAX_RUN_VIEW_PASSAGE_BYTES_CEILING}
              placeholder={m.flow_knowledge_evidence_default_hint()}
              aria-describedby="max-run-view-bytes-ceiling"
              bind:value={maxRunViewPassageBytes}
            />
            <p class="text-secondary text-xs">{formatBytePreview(maxRunViewPassageBytes)}</p>
            <p id="max-run-view-bytes-ceiling" class="text-secondary text-xs">
              {m.flow_knowledge_evidence_ceiling_bytes_hint({
                ceiling: formatBytes(MAX_RUN_VIEW_PASSAGE_BYTES_CEILING)
              })}
            </p>
          </div>
        </Settings.Row>
      </Settings.Group>

      <div class="flex justify-end px-1 py-4">
        <Button variant="primary" disabled={isSaving} onclick={savePolicy}>
          {isSaving ? m.saving() : m.save()}
        </Button>
      </div>
    </Settings.Page>
  </Page.Main>
</Page.Root>
