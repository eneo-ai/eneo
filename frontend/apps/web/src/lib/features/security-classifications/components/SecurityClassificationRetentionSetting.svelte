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
    FlowRetentionImpactPreview
  } from "@eneo/eneo-js";
  import FlowRetentionImpactDialog from "$lib/features/flows/components/FlowRetentionImpactDialog.svelte";
  import { confirmationFromFlowRetentionPreview } from "$lib/features/flows/flowRetentionPolicy";
  import { getSecurityClassificationService } from "../SecurityClassificationsService.svelte";
  import {
    buildFlowClassificationRetentionRows,
    clearFlowClassificationRetentionPolicyDraft,
    createFlowClassificationRetentionDrafts,
    flowClassificationRetentionChangeIsDestructive,
    FLOW_CLASSIFICATION_RETENTION_MAX_DAYS,
    FLOW_CLASSIFICATION_RETENTION_MIN_DAYS,
    parseFlowClassificationRetentionDays,
    setFlowClassificationRetentionPolicyDraft,
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

  function getValidationMessage(row: FlowClassificationRetentionRow) {
    const parsed = parseFlowClassificationRetentionDays(row.draftDays);
    if (parsed.ok || parsed.reason === "empty") return null;
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
      row.hasChanges &&
      !savingById[row.id] &&
      !clearingById[row.id]
    );
  }

  async function savePolicy(row: FlowClassificationRetentionRow) {
    const parsed = parseFlowClassificationRetentionDays(row.draftDays);
    if (!parsed.ok) return;

    savingById = setBusy(savingById, row.id, true);
    try {
      if (flowClassificationRetentionChangeIsDestructive(row.configuredDays, parsed.days)) {
        preview = await eneo.settings.previewFlowClassificationRetentionPolicy(row.id, {
          data_retention_days: parsed.days
        });
        pendingRow = row;
        previewOpen = true;
        return;
      }
      const policy = await eneo.settings.putFlowClassificationRetentionPolicy(row.id, {
        data_retention_days: parsed.days
      });
      drafts = setFlowClassificationRetentionPolicyDraft(drafts, policy);
      toast.success(m.saved_successfully());
    } catch (error) {
      toastError(error);
    } finally {
      savingById = setBusy(savingById, row.id, false);
    }
  }

  async function confirmPolicy() {
    if (!preview || !pendingRow) return;
    const parsed = parseFlowClassificationRetentionDays(pendingRow.draftDays);
    if (!parsed.ok) return;
    const rowId = pendingRow.id;

    savingById = setBusy(savingById, rowId, true);
    try {
      const policy = await eneo.settings.putFlowClassificationRetentionPolicy(rowId, {
        data_retention_days: parsed.days,
        confirmation: confirmationFromFlowRetentionPreview(preview)
      });
      drafts = setFlowClassificationRetentionPolicyDraft(drafts, policy);
      previewOpen = false;
      preview = null;
      pendingRow = null;
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
      await eneo.settings.deleteFlowClassificationRetentionPolicy(row.id);
      drafts = clearFlowClassificationRetentionPolicyDraft(drafts, row.id);
      toast.success(m.saved_successfully());
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
        <table class="w-full min-w-[720px] text-left text-sm">
          <thead class="bg-secondary text-secondary">
            <tr>
              <th class="px-4 py-3 font-medium">
                {m.security_classification()}
              </th>
              <th class="px-4 py-3 font-medium">
                {m.flow_classification_retention_current_policy()}
              </th>
              <th class="px-4 py-3 font-medium">
                {m.flow_classification_retention_days_label()}
              </th>
              <th class="px-4 py-3 text-right font-medium">
                {m.actions()}
              </th>
            </tr>
          </thead>
          <tbody>
            {#each rows as row (row.id)}
              {@const validationMessage = getValidationMessage(row)}
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
                  {#if row.hasPolicy && row.configuredDays !== null}
                    <span class="text-primary">
                      {m.flow_classification_retention_days_value({
                        days: row.configuredDays
                      })}
                    </span>
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
