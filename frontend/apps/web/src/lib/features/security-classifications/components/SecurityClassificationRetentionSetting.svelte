<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { toast } from "$lib/components/toast";
  import { getEneo } from "$lib/core/Eneo";
  import { toastError } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { Button } from "@eneo/ui";
  import type {
    FlowClassificationRetentionPolicies,
    FlowClassificationRetentionPolicyPreviewRequest,
    FlowRetentionImpactPreview
  } from "@eneo/eneo-js";
  import FlowRetentionImpactDialog from "$lib/features/flows/components/FlowRetentionImpactDialog.svelte";
  import { confirmationFromFlowRetentionPreview } from "$lib/features/flows/flowRetentionPolicy";
  import { getSecurityClassificationService } from "../SecurityClassificationsService.svelte";
  import {
    buildFlowClassificationRetentionRows,
    clearFlowClassificationRetentionPolicyDraft,
    createFlowClassificationRetentionDrafts,
    FLOW_CLASSIFICATION_RETENTION_MAX_DAYS,
    FLOW_CLASSIFICATION_RETENTION_MIN_DAYS,
    parseFlowClassificationRetentionDays,
    setFlowClassificationRetentionPolicyDraft,
    updateFlowClassificationMinimumRetentionDraft,
    updateFlowClassificationNoPurgeDraft,
    updateFlowClassificationRetentionDraft,
    type FlowClassificationRetentionDrafts,
    type FlowClassificationRetentionRow
  } from "../flowClassificationRetentionPolicy";

  type Props = {
    initialPolicies: FlowClassificationRetentionPolicies;
  };

  let { initialPolicies }: Props = $props();
  const eneo = getEneo();
  const security = getSecurityClassificationService();

  let drafts = $derived<FlowClassificationRetentionDrafts>(
    createFlowClassificationRetentionDrafts(initialPolicies.policies)
  );
  let savingById = $state<Record<string, boolean>>({});
  let clearingById = $state<Record<string, boolean>>({});
  let preview = $state<FlowRetentionImpactPreview | null>(null);
  let pendingRow = $state<FlowClassificationRetentionRow | null>(null);
  let pendingProposal = $state<FlowClassificationRetentionPolicyPreviewRequest | null>(null);
  let previewOpen = $state(false);

  let rows = $derived(buildFlowClassificationRetentionRows(security.classifications, drafts));
  let isSecurityEnabled = $derived(security.isSecurityEnabled);

  function setBusy(
    busyById: Record<string, boolean>,
    securityClassificationId: string,
    isBusy: boolean
  ) {
    const next = { ...busyById };
    if (isBusy) {
      next[securityClassificationId] = true;
    } else {
      delete next[securityClassificationId];
    }
    return next;
  }

  function updateDraft(securityClassificationId: string, event: Event) {
    const input = event.currentTarget;
    if (!(input instanceof HTMLInputElement)) return;
    drafts = updateFlowClassificationRetentionDraft(drafts, securityClassificationId, input.value);
  }

  function updateMinimumDraft(securityClassificationId: string, event: Event) {
    const input = event.currentTarget;
    if (!(input instanceof HTMLInputElement)) return;
    drafts = updateFlowClassificationMinimumRetentionDraft(
      drafts,
      securityClassificationId,
      input.value
    );
  }

  function updateNoPurgeDraft(securityClassificationId: string, event: Event) {
    const input = event.currentTarget;
    if (!(input instanceof HTMLInputElement)) return;
    drafts = updateFlowClassificationNoPurgeDraft(drafts, securityClassificationId, input.checked);
  }

  function getValidationMessage(value: string) {
    const parsed = parseFlowClassificationRetentionDays(value);
    if (parsed.ok) return null;
    if (parsed.reason === "integer") {
      return m.flow_classification_retention_validation_integer();
    }
    return m.flow_classification_retention_validation_range({
      min: FLOW_CLASSIFICATION_RETENTION_MIN_DAYS,
      max: FLOW_CLASSIFICATION_RETENTION_MAX_DAYS
    });
  }

  function canSave(row: FlowClassificationRetentionRow) {
    return (
      parseFlowClassificationRetentionDays(row.draftDays).ok &&
      parseFlowClassificationRetentionDays(row.draftMinimumDays).ok &&
      row.hasChanges &&
      !savingById[row.id] &&
      !clearingById[row.id]
    );
  }

  function desiredState(
    row: FlowClassificationRetentionRow
  ): FlowClassificationRetentionPolicyPreviewRequest | null {
    const deleteAfter = parseFlowClassificationRetentionDays(row.draftDays);
    const minimum = parseFlowClassificationRetentionDays(row.draftMinimumDays);
    if (!deleteAfter.ok || !minimum.ok) return null;
    return {
      data_retention_days: deleteAfter.days,
      minimum_retention_days: minimum.days,
      no_purge: row.draftNoPurge
    };
  }

  async function previewPolicy(
    row: FlowClassificationRetentionRow,
    proposal: FlowClassificationRetentionPolicyPreviewRequest
  ) {
    preview = await eneo.settings.previewFlowClassificationRetentionPolicy(row.id, proposal);
    pendingRow = row;
    pendingProposal = proposal;
    previewOpen = true;
  }

  async function savePolicy(row: FlowClassificationRetentionRow) {
    const proposal = desiredState(row);
    if (!proposal) return;

    savingById = setBusy(savingById, row.id, true);
    try {
      await previewPolicy(row, proposal);
    } catch (error) {
      toastError(error);
    } finally {
      savingById = setBusy(savingById, row.id, false);
    }
  }

  async function confirmPolicy() {
    if (!preview || !pendingRow || !pendingProposal) return;
    const rowId = pendingRow.id;

    savingById = setBusy(savingById, rowId, true);
    try {
      const policy = await eneo.settings.putFlowClassificationRetentionPolicy(rowId, {
        ...pendingProposal,
        confirmation: confirmationFromFlowRetentionPreview(preview)
      });
      drafts = policy
        ? setFlowClassificationRetentionPolicyDraft(drafts, policy)
        : clearFlowClassificationRetentionPolicyDraft(drafts, rowId);
      previewOpen = false;
      preview = null;
      pendingRow = null;
      pendingProposal = null;
      toast.success(m.saved_successfully());
    } catch (error) {
      toastError(error);
    } finally {
      savingById = setBusy(savingById, rowId, false);
    }
  }

  async function clearPolicy(row: FlowClassificationRetentionRow) {
    if (!row.hasPolicy || savingById[row.id] || clearingById[row.id]) return;

    clearingById = setBusy(clearingById, row.id, true);
    try {
      await previewPolicy(row, {
        data_retention_days: null,
        minimum_retention_days: null,
        no_purge: false
      });
    } catch (error) {
      toastError(error);
    } finally {
      clearingById = setBusy(clearingById, row.id, false);
    }
  }
</script>

<Settings.Row
  fullWidth
  title={m.flow_classification_retention_row_title()}
  description={m.flow_classification_retention_description()}
>
  <div class="flex flex-col gap-4">
    <div class="text-secondary flex flex-col gap-2 text-sm leading-relaxed">
      <p>{m.flow_classification_retention_full_history_hint()}</p>
      <p>{m.flow_classification_retention_tighten_hint()}</p>
      {#if !isSecurityEnabled}
        <p class="border-default bg-secondary rounded-md border px-3 py-2">
          {m.flow_classification_retention_security_disabled_hint()}
        </p>
      {/if}
    </div>

    {#if rows.length > 0}
      <div class="border-default overflow-x-auto rounded-lg border">
        <table class="w-full min-w-[980px] text-left text-sm">
          <thead class="bg-secondary text-secondary">
            <tr>
              <th class="px-4 py-3 font-medium">
                {m.security_classification()}
              </th>
              <th class="px-4 py-3 font-medium">
                {m.flow_classification_retention_current_policy()}
              </th>
              <th class="px-4 py-3 font-medium">
                {m.flow_classification_retention_delete_after_label()}
              </th>
              <th class="px-4 py-3 font-medium">
                {m.flow_classification_retention_minimum_label()}
              </th>
              <th class="px-4 py-3 font-medium">
                {m.flow_classification_retention_no_purge_label()}
              </th>
              <th class="px-4 py-3 text-right font-medium">
                {m.actions()}
              </th>
            </tr>
          </thead>
          <tbody>
            {#each rows as row (row.id)}
              {@const validationMessage = getValidationMessage(row.draftDays)}
              {@const minimumValidationMessage = getValidationMessage(row.draftMinimumDays)}
              {@const validationMessageId = `flow-classification-retention-${row.id}-error`}
              <tr class="border-default border-t align-top">
                <td class="px-4 py-4">
                  <div class="flex flex-col gap-1">
                    <span class="text-primary font-semibold">{row.name}</span>
                    {#if row.description}
                      <span class="text-secondary max-w-xl text-xs leading-relaxed">
                        {row.description}
                      </span>
                    {/if}
                  </div>
                </td>
                <td class="px-4 py-4">
                  {#if row.hasPolicy}
                    <div class="text-primary grid gap-1 text-xs">
                      <span
                        >{m.flow_classification_retention_delete_after_value({
                          value: row.configuredDays ?? "—"
                        })}</span
                      >
                      <span
                        >{m.flow_classification_retention_minimum_value({
                          value: row.configuredMinimumDays ?? "—"
                        })}</span
                      >
                      <span
                        >{row.configuredNoPurge
                          ? m.flow_classification_retention_no_purge_on()
                          : m.flow_classification_retention_no_purge_off()}</span
                      >
                    </div>
                  {:else}
                    <span class="text-secondary">
                      {m.flow_classification_retention_no_policy()}
                    </span>
                  {/if}
                </td>
                <td class="px-4 py-4">
                  <div class="flex max-w-xs flex-col gap-1">
                    <input
                      class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
                      type="number"
                      min={FLOW_CLASSIFICATION_RETENTION_MIN_DAYS}
                      max={FLOW_CLASSIFICATION_RETENTION_MAX_DAYS}
                      step="1"
                      value={row.draftDays}
                      placeholder={m.flow_classification_retention_no_policy()}
                      aria-label={m.flow_classification_retention_input_label({
                        name: row.name
                      })}
                      aria-invalid={validationMessage ? "true" : undefined}
                      aria-describedby={validationMessage ? validationMessageId : undefined}
                      oninput={(event) => updateDraft(row.id, event)}
                    />
                    {#if validationMessage}
                      <p id={validationMessageId} class="text-negative-default text-xs">
                        {validationMessage}
                      </p>
                    {/if}
                  </div>
                </td>
                <td class="px-4 py-4">
                  <div class="flex max-w-xs flex-col gap-1">
                    <input
                      class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2"
                      type="number"
                      min={FLOW_CLASSIFICATION_RETENTION_MIN_DAYS}
                      max={FLOW_CLASSIFICATION_RETENTION_MAX_DAYS}
                      step="1"
                      value={row.draftMinimumDays}
                      placeholder={m.flow_classification_retention_no_minimum()}
                      aria-label={m.flow_classification_retention_minimum_input_label({
                        name: row.name
                      })}
                      aria-invalid={minimumValidationMessage ? "true" : undefined}
                      oninput={(event) => updateMinimumDraft(row.id, event)}
                    />
                    {#if minimumValidationMessage}
                      <p class="text-negative-default text-xs">{minimumValidationMessage}</p>
                    {/if}
                  </div>
                </td>
                <td class="px-4 py-4">
                  <label class="text-primary flex items-center gap-2">
                    <input
                      class="size-4"
                      type="checkbox"
                      checked={row.draftNoPurge}
                      onchange={(event) => updateNoPurgeDraft(row.id, event)}
                    />
                    <span>{m.flow_classification_retention_no_purge_checkbox()}</span>
                  </label>
                </td>
                <td class="px-4 py-4">
                  <div class="flex justify-end gap-2">
                    <Button
                      variant="outlined"
                      onclick={() => clearPolicy(row)}
                      disabled={!row.hasPolicy || savingById[row.id] || clearingById[row.id]}
                    >
                      {clearingById[row.id]
                        ? m.flow_classification_retention_clearing()
                        : m.clear()}
                    </Button>
                    <Button
                      variant="primary"
                      onclick={() => savePolicy(row)}
                      disabled={!canSave(row)}
                    >
                      {savingById[row.id] ? m.saving() : m.save()}
                    </Button>
                  </div>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {:else}
      <div class="text-muted border-default rounded-lg border px-4 py-6 text-sm">
        {m.flow_classification_retention_empty_classifications()}
      </div>
    {/if}
  </div>
</Settings.Row>

{#if preview}
  <FlowRetentionImpactDialog
    bind:open={previewOpen}
    {preview}
    confirming={pendingRow ? Boolean(savingById[pendingRow.id]) : false}
    onConfirm={confirmPolicy}
  />
{/if}
