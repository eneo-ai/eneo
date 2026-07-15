<script lang="ts">
  import type {
    FlowRetentionImpactPreview,
    FlowRetentionPolicy,
    FlowRetentionPolicyUpdate
  } from "@eneo/eneo-js";
  import { Button } from "@eneo/ui";
  import { resolve } from "$app/paths";
  import { Page, Settings } from "$lib/components/layout";
  import { toast } from "$lib/components/toast";
  import { getEneo } from "$lib/core/Eneo";
  import { toastError } from "$lib/core/errors";
  import FlowRetentionImpactDialog from "$lib/features/flows/components/FlowRetentionImpactDialog.svelte";
  import {
    confirmationFromFlowRetentionPreview,
    FLOW_RETENTION_MAX_DAYS,
    FLOW_RETENTION_MIN_DAYS,
    organizationRetentionChangeIsDestructive,
    parseFlowRetentionDays
  } from "$lib/features/flows/flowRetentionPolicy";
  import { m } from "$lib/paraglide/messages";

  let { data } = $props();
  const eneo = getEneo();

  let policy = $derived<FlowRetentionPolicy>(data.flowRetentionPolicy);
  let runHistoryDays = $derived(policy.flow_run_history_retention_days?.toString() ?? "");
  let minimumDays = $derived(policy.flow_run_history_minimum_retention_days?.toString() ?? "");
  let noPurge = $derived(policy.flow_run_history_no_purge);
  let uploadDays = $derived(policy.flow_runtime_upload_abandonment_days?.toString() ?? "");
  let saving = $state(false);
  let preview = $state<FlowRetentionImpactPreview | null>(null);
  let previewOpen = $state(false);

  let parsedRunHistory = $derived(parseFlowRetentionDays(runHistoryDays));
  let parsedUpload = $derived(parseFlowRetentionDays(uploadDays));
  let parsedMinimum = $derived(parseFlowRetentionDays(minimumDays));
  let valid = $derived(parsedRunHistory.ok && parsedUpload.ok && parsedMinimum.ok);
  let changed = $derived.by(() => {
    if (!parsedRunHistory.ok || !parsedUpload.ok || !parsedMinimum.ok) return false;
    return (
      parsedRunHistory.days !== policy.flow_run_history_retention_days ||
      parsedUpload.days !== policy.flow_runtime_upload_abandonment_days ||
      parsedMinimum.days !== policy.flow_run_history_minimum_retention_days ||
      noPurge !== policy.flow_run_history_no_purge
    );
  });

  function applyPolicy(updated: FlowRetentionPolicy) {
    policy = updated;
    runHistoryDays = updated.flow_run_history_retention_days?.toString() ?? "";
    minimumDays = updated.flow_run_history_minimum_retention_days?.toString() ?? "";
    noPurge = updated.flow_run_history_no_purge;
    uploadDays = updated.flow_runtime_upload_abandonment_days?.toString() ?? "";
  }

  function updateRunHistoryDays(event: Event) {
    const input = event.currentTarget;
    if (input instanceof HTMLInputElement) runHistoryDays = input.value;
  }

  function updateUploadDays(event: Event) {
    const input = event.currentTarget;
    if (input instanceof HTMLInputElement) uploadDays = input.value;
  }

  function updateMinimumDays(event: Event) {
    const input = event.currentTarget;
    if (input instanceof HTMLInputElement) minimumDays = input.value;
  }

  function updateNoPurge(event: Event) {
    const input = event.currentTarget;
    if (input instanceof HTMLInputElement) noPurge = input.checked;
  }

  function proposal(): FlowRetentionPolicyUpdate | null {
    if (!parsedRunHistory.ok || !parsedUpload.ok || !parsedMinimum.ok) return null;
    return {
      flow_run_history_retention_days: parsedRunHistory.days,
      flow_run_history_minimum_retention_days: parsedMinimum.days,
      flow_run_history_no_purge: noPurge,
      flow_runtime_upload_abandonment_days: parsedUpload.days
    };
  }

  async function save() {
    const next = proposal();
    if (!next || !changed || saving) return;
    saving = true;
    try {
      if (
        organizationRetentionChangeIsDestructive(
          policy,
          next.flow_run_history_retention_days ?? null,
          next.flow_runtime_upload_abandonment_days ?? null,
          next.flow_run_history_minimum_retention_days ?? null,
          next.flow_run_history_no_purge ?? false
        )
      ) {
        preview = await eneo.settings.previewFlowRetentionPolicy({
          flow_run_history_retention_days: next.flow_run_history_retention_days ?? null,
          flow_run_history_minimum_retention_days:
            next.flow_run_history_minimum_retention_days ?? null,
          flow_run_history_no_purge: next.flow_run_history_no_purge ?? false,
          flow_runtime_upload_abandonment_days: next.flow_runtime_upload_abandonment_days ?? null
        });
        previewOpen = true;
        return;
      }
      applyPolicy(await eneo.settings.updateFlowRetentionPolicy(next));
      toast.success(m.saved_successfully());
    } catch (error) {
      toastError(error);
    } finally {
      saving = false;
    }
  }

  async function confirmDestructiveChange() {
    const next = proposal();
    if (!next || !preview || saving) return;
    saving = true;
    try {
      applyPolicy(
        await eneo.settings.updateFlowRetentionPolicy({
          ...next,
          confirmation: confirmationFromFlowRetentionPreview(preview)
        })
      );
      previewOpen = false;
      preview = null;
      toast.success(m.saved_successfully());
    } catch (error) {
      toastError(error);
    } finally {
      saving = false;
    }
  }

  function validationMessage(parsed: typeof parsedRunHistory): string | null {
    if (parsed.ok) return null;
    if (parsed.reason === "integer") return m.flow_retention_validation_integer();
    return m.flow_retention_validation_range({
      min: FLOW_RETENTION_MIN_DAYS,
      max: FLOW_RETENTION_MAX_DAYS
    });
  }
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.flow_retention_title()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.flow_retention_title()} />
  </Page.Header>
  <Page.Main>
    <Settings.Page>
      <Settings.Group title={m.flow_retention_organization_group()}>
        <Settings.Row
          title={m.flow_retention_run_history_title()}
          description={m.flow_retention_run_history_description()}
        >
          <div class="flex w-full max-w-sm flex-col gap-1">
            <input
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
              type="number"
              min={FLOW_RETENTION_MIN_DAYS}
              max={FLOW_RETENTION_MAX_DAYS}
              step="1"
              placeholder={m.flow_retention_off()}
              aria-label={m.flow_retention_run_history_title()}
              value={runHistoryDays}
              oninput={updateRunHistoryDays}
              aria-invalid={validationMessage(parsedRunHistory) ? "true" : undefined}
            />
            <p class="text-secondary text-xs">
              {runHistoryDays.trim() ? m.flow_retention_days_suffix() : m.flow_retention_off()}
            </p>
            {#if validationMessage(parsedRunHistory)}
              <p class="text-negative-default text-xs">{validationMessage(parsedRunHistory)}</p>
            {/if}
          </div>
        </Settings.Row>

        <Settings.Row
          title={m.flow_retention_minimum_title()}
          description={m.flow_retention_minimum_description()}
        >
          <div class="flex w-full max-w-sm flex-col gap-1">
            <input
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
              type="number"
              min={FLOW_RETENTION_MIN_DAYS}
              max={FLOW_RETENTION_MAX_DAYS}
              step="1"
              placeholder={m.flow_retention_no_minimum()}
              aria-label={m.flow_retention_minimum_title()}
              value={minimumDays}
              oninput={updateMinimumDays}
              aria-invalid={validationMessage(parsedMinimum) ? "true" : undefined}
            />
            <p class="text-secondary text-xs">
              {minimumDays.trim() ? m.flow_retention_days_suffix() : m.flow_retention_no_minimum()}
            </p>
            {#if validationMessage(parsedMinimum)}
              <p class="text-negative-default text-xs">{validationMessage(parsedMinimum)}</p>
            {/if}
          </div>
        </Settings.Row>

        <Settings.Row
          title={m.flow_retention_no_purge_title()}
          description={m.flow_retention_no_purge_description()}
        >
          <label class="text-primary flex w-full max-w-sm items-center gap-3 text-sm">
            <input class="size-4" type="checkbox" checked={noPurge} onchange={updateNoPurge} />
            <span>{m.flow_retention_no_purge_checkbox()}</span>
          </label>
        </Settings.Row>

        <Settings.Row
          title={m.flow_retention_upload_title()}
          description={m.flow_retention_upload_description()}
        >
          <div class="flex w-full max-w-sm flex-col gap-1">
            <input
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
              type="number"
              min={FLOW_RETENTION_MIN_DAYS}
              max={FLOW_RETENTION_MAX_DAYS}
              step="1"
              placeholder={m.flow_retention_off()}
              aria-label={m.flow_retention_upload_title()}
              value={uploadDays}
              oninput={updateUploadDays}
              aria-invalid={validationMessage(parsedUpload) ? "true" : undefined}
            />
            <p class="text-secondary text-xs">
              {uploadDays.trim() ? m.flow_retention_days_suffix() : m.flow_retention_off()}
            </p>
            {#if validationMessage(parsedUpload)}
              <p class="text-negative-default text-xs">{validationMessage(parsedUpload)}</p>
            {/if}
          </div>
        </Settings.Row>
      </Settings.Group>

      <Settings.Group title={m.flow_retention_effective_group()}>
        <Settings.Row
          fullWidth
          title={m.flow_retention_effective_title()}
          description={m.flow_retention_effective_description()}
        >
          <div class="text-secondary grid gap-2 text-sm sm:grid-cols-2">
            <p>
              {m.flow_retention_run_history_title()}:
              <strong class="text-primary">
                {policy.effective_state.run_history_deletion_active
                  ? m.flow_retention_active()
                  : m.flow_retention_off()}
              </strong>
            </p>
            <p>
              {m.flow_retention_upload_title()}:
              <strong class="text-primary">
                {policy.effective_state.runtime_upload_abandonment_active
                  ? m.flow_retention_active()
                  : m.flow_retention_off()}
              </strong>
            </p>
            <p class="sm:col-span-2">
              {m.flow_retention_classification_policy_count({
                count: policy.effective_state.classification_policy_count
              })}
            </p>
          </div>
        </Settings.Row>

        <Settings.Row
          fullWidth
          title={m.flow_retention_clock_title()}
          description={m.flow_retention_clock_description()}
        >
          <div class="text-secondary grid gap-2 text-sm">
            <p>{m.flow_retention_run_anchor_description()}</p>
            <p>{m.flow_retention_upload_anchor_description()}</p>
          </div>
        </Settings.Row>

        <Settings.Row
          fullWidth
          title={m.flow_retention_audit_title()}
          description={m.flow_retention_audit_description()}
        />
      </Settings.Group>

      <Settings.Group title={m.flow_retention_safety_group()}>
        <Settings.Row
          fullWidth
          title={m.flow_retention_preservation_title()}
          description={m.flow_retention_preservation_hold_caveat()}
        >
          <div class="flex flex-wrap items-center justify-between gap-4">
            <p class="text-secondary max-w-2xl text-sm leading-relaxed">
              {m.flow_retention_classification_hint()}
            </p>
            <a
              class="text-accent-default font-medium hover:underline"
              href={resolve("/(app)/admin/security-classifications")}
            >
              {m.flow_retention_manage_classifications()}
            </a>
          </div>
        </Settings.Row>
      </Settings.Group>

      <div class="flex justify-end">
        <Button variant="primary" onclick={save} disabled={!changed || !valid || saving}>
          {saving ? m.saving() : m.save()}
        </Button>
      </div>
    </Settings.Page>
  </Page.Main>
</Page.Root>

{#if preview}
  <FlowRetentionImpactDialog
    bind:open={previewOpen}
    {preview}
    confirming={saving}
    onConfirm={confirmDestructiveChange}
  />
{/if}
