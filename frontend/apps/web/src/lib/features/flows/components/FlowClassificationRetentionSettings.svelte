<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type {
    FlowClassificationRetentionPolicies,
    FlowClassificationRetentionPolicyPreviewRequest,
    FlowRetentionImpactPreview,
    SecurityClassification
  } from "@eneo/eneo-js";
  import { onDestroy, untrack } from "svelte";
  import Pencil from "lucide-svelte/icons/pencil";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as InputGroup from "$lib/components/ui/input-group/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { toast } from "$lib/components/toast";
  import { getEneo } from "$lib/core/Eneo";
  import { toastError } from "$lib/core/errors";
  import FlowRetentionImpactDialog from "$lib/features/flows/components/FlowRetentionImpactDialog.svelte";
  import {
    buildFlowClassificationRetentionRows,
    clearFlowClassificationRetentionPolicyDraft,
    createFlowClassificationRetentionDrafts,
    flowClassificationRetentionChangeRequiresConfirmation,
    FLOW_CLASSIFICATION_RETENTION_MAX_DAYS,
    FLOW_CLASSIFICATION_RETENTION_MIN_DAYS,
    parseFlowClassificationRetentionDays,
    setFlowClassificationRetentionPolicyDraft,
    updateFlowClassificationMinimumRetentionDraft,
    updateFlowClassificationNoPurgeDraft,
    updateFlowClassificationRetentionDraft,
    type FlowClassificationRetentionDrafts,
    type FlowClassificationRetentionRow
  } from "$lib/features/flows/flowClassificationRetentionPolicy";
  import { confirmationFromFlowRetentionPreview } from "$lib/features/flows/flowRetentionPolicy";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    initialPolicies: FlowClassificationRetentionPolicies;
    classifications: SecurityClassification[];
    securityEnabled: boolean;
    onDirtyCountChange?: (count: number) => void;
    onPoliciesChanged?: () => void | Promise<void>;
  };

  let {
    initialPolicies,
    classifications,
    securityEnabled,
    onDirtyCountChange,
    onPoliciesChanged
  }: Props = $props();
  const eneo = getEneo();

  const initialDrafts = untrack(() =>
    createFlowClassificationRetentionDrafts(initialPolicies.policies)
  );
  let drafts = $state<FlowClassificationRetentionDrafts>(initialDrafts);
  let editorOpen = $state(false);
  let activeRowId = $state<string | null>(null);
  let savingById = $state<Record<string, boolean>>({});
  let clearingById = $state<Record<string, boolean>>({});
  let preview = $state<FlowRetentionImpactPreview | null>(null);
  let pendingRow = $state<FlowClassificationRetentionRow | null>(null);
  let pendingProposal = $state<FlowClassificationRetentionPolicyPreviewRequest | null>(null);
  let previewOpen = $state(false);

  let rows = $derived(buildFlowClassificationRetentionRows(classifications.toReversed(), drafts));
  let activeRow = $derived(rows.find((row) => row.id === activeRowId) ?? null);
  let dirtyCount = $derived(rows.filter((row) => row.hasChanges).length);

  $effect(() => {
    onDirtyCountChange?.(dirtyCount);
  });

  onDestroy(() => onDirtyCountChange?.(0));

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

  function openEditor(row: FlowClassificationRetentionRow) {
    activeRowId = row.id;
    editorOpen = true;
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

  function updateNoPurgeDraft(securityClassificationId: string, checked: boolean) {
    drafts = updateFlowClassificationNoPurgeDraft(drafts, securityClassificationId, checked);
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

  function resetDraft(row: FlowClassificationRetentionRow) {
    drafts = row.hasPolicy
      ? setFlowClassificationRetentionPolicyDraft(drafts, {
          security_classification_id: row.id,
          data_retention_days: row.configuredDays,
          minimum_retention_days: row.configuredMinimumDays,
          no_purge: row.configuredNoPurge
        })
      : clearFlowClassificationRetentionPolicyDraft(drafts, row.id);
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

  async function notifyPoliciesChanged() {
    try {
      await onPoliciesChanged?.();
    } catch (error) {
      toastError(error);
    }
  }

  async function savePolicy(row: FlowClassificationRetentionRow) {
    const proposal = desiredState(row);
    if (!proposal) return;

    savingById = setBusy(savingById, row.id, true);
    try {
      const currentPolicy = row.hasPolicy
        ? {
            security_classification_id: row.id,
            data_retention_days: row.configuredDays,
            minimum_retention_days: row.configuredMinimumDays,
            no_purge: row.configuredNoPurge
          }
        : null;
      if (flowClassificationRetentionChangeRequiresConfirmation(currentPolicy, proposal)) {
        await previewPolicy(row, proposal);
        return;
      }

      const policy = await eneo.settings.putFlowClassificationRetentionPolicy(row.id, proposal);
      drafts = policy
        ? setFlowClassificationRetentionPolicyDraft(drafts, policy)
        : clearFlowClassificationRetentionPolicyDraft(drafts, row.id);
      await notifyPoliciesChanged();
      editorOpen = false;
      toast.success(m.saved_successfully());
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
      await notifyPoliciesChanged();
      previewOpen = false;
      editorOpen = false;
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

  function configuredDays(value: number | null): string {
    return value == null
      ? m.flow_classification_retention_inherited()
      : m.flow_classification_retention_days({ days: value });
  }
</script>

<div class="flex flex-col gap-4 px-4 pb-2 lg:px-0.5">
  <div class="max-w-3xl">
    <h3 class="text-primary text-sm font-semibold">
      {m.flow_classification_retention_row_title()}
    </h3>
    <p class="text-secondary mt-1 text-sm leading-relaxed">
      {m.flow_classification_retention_description()}
    </p>
  </div>
  <p class="text-secondary max-w-3xl text-sm leading-relaxed">
    {m.flow_classification_retention_precedence_hint()}
  </p>
  {#if !securityEnabled}
    <Alert.Root>
      <Alert.Description>
        {m.flow_classification_retention_security_disabled_hint()}
      </Alert.Description>
    </Alert.Root>
  {/if}

  {#if rows.length > 0}
    <div class="border-default overflow-hidden rounded-lg border">
      <Table.Root class="min-w-[46rem]">
        <Table.Header>
          <Table.Row class="bg-muted/40 hover:bg-muted/40">
            <Table.Head>{m.flow_classification_retention_table_classification()}</Table.Head>
            <Table.Head>{m.flow_classification_retention_delete_after_label()}</Table.Head>
            <Table.Head>{m.flow_classification_retention_minimum_label()}</Table.Head>
            <Table.Head>{m.flow_classification_retention_pause_label()}</Table.Head>
            <Table.Head class="w-28 text-right">{m.actions()}</Table.Head>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {#each rows as row (row.id)}
            <Table.Row>
              <Table.Cell class="max-w-64 py-3 align-top">
                <div class="flex min-w-0 flex-col gap-1">
                  <div class="flex items-center gap-2">
                    <span class="text-primary truncate font-medium">{row.name}</span>
                    {#if row.hasChanges}
                      <Badge variant="outline">{m.flow_classification_retention_unsaved()}</Badge>
                    {/if}
                  </div>
                  {#if row.description}
                    <span class="text-secondary truncate text-xs">{row.description}</span>
                  {/if}
                </div>
              </Table.Cell>
              <Table.Cell class="text-secondary py-3 align-top">
                {configuredDays(row.configuredDays)}
              </Table.Cell>
              <Table.Cell class="text-secondary py-3 align-top">
                {configuredDays(row.configuredMinimumDays)}
              </Table.Cell>
              <Table.Cell class="py-3 align-top">
                <Badge variant={row.configuredNoPurge ? "secondary" : "outline"}>
                  {row.configuredNoPurge
                    ? m.flow_classification_retention_paused()
                    : m.flow_classification_retention_not_paused()}
                </Badge>
              </Table.Cell>
              <Table.Cell class="py-3 text-right align-top">
                <Button
                  variant="outline"
                  size="sm"
                  aria-label={m.flow_classification_retention_edit_label({ name: row.name })}
                  onclick={() => openEditor(row)}
                >
                  <Pencil aria-hidden="true" />
                  {m.edit()}
                </Button>
              </Table.Cell>
            </Table.Row>
          {/each}
        </Table.Body>
      </Table.Root>
    </div>
  {:else}
    <div class="text-secondary border-default rounded-lg border px-4 py-6 text-sm">
      {m.flow_classification_retention_empty_classifications()}
    </div>
  {/if}
</div>

<Dialog.Root bind:open={editorOpen}>
  <Dialog.Content
    class="max-h-[calc(100vh-2rem)] gap-0 overflow-hidden p-0 sm:max-w-2xl"
    closeLabel={m.aria_close()}
  >
    {#if activeRow}
      {@const validationMessage = getValidationMessage(activeRow.draftDays)}
      {@const minimumValidationMessage = getValidationMessage(activeRow.draftMinimumDays)}
      {@const validationMessageId = `flow-classification-retention-${activeRow.id}-error`}
      {@const minimumValidationMessageId = `flow-classification-minimum-${activeRow.id}-error`}
      {@const deleteAfterId = `flow-classification-delete-after-${activeRow.id}`}
      {@const minimumId = `flow-classification-minimum-${activeRow.id}`}
      {@const noPurgeId = `flow-classification-no-purge-${activeRow.id}`}

      <Dialog.Header class="px-6 pt-6 pr-14 pb-5">
        <Dialog.Title class="text-lg font-semibold">
          {m.flow_classification_retention_dialog_title({ name: activeRow.name })}
        </Dialog.Title>
        <Dialog.Description class="leading-relaxed">
          {m.flow_classification_retention_sheet_description()}
        </Dialog.Description>
      </Dialog.Header>

      <div class="grid flex-1 gap-x-6 gap-y-7 overflow-y-auto px-6 py-5 sm:grid-cols-2">
        <div class="flex min-w-0 flex-col gap-2">
          <Label for={deleteAfterId}>
            {m.flow_classification_retention_delete_after_label()}
          </Label>
          <InputGroup.Root>
            <InputGroup.Input
              id={deleteAfterId}
              type="number"
              min={FLOW_CLASSIFICATION_RETENTION_MIN_DAYS}
              max={FLOW_CLASSIFICATION_RETENTION_MAX_DAYS}
              step="1"
              value={activeRow.draftDays}
              placeholder={m.flow_classification_retention_no_policy()}
              aria-label={m.flow_classification_retention_input_label({ name: activeRow.name })}
              aria-invalid={validationMessage ? true : undefined}
              aria-describedby={validationMessage ? validationMessageId : undefined}
              oninput={(event) => updateDraft(activeRow.id, event)}
            />
            <InputGroup.Addon align="inline-end">
              <InputGroup.Text>{m.flow_retention_days_suffix()}</InputGroup.Text>
            </InputGroup.Addon>
          </InputGroup.Root>
          <p class="text-secondary text-xs leading-relaxed">
            {m.flow_classification_retention_delete_after_help()}
          </p>
          {#if validationMessage}
            <p id={validationMessageId} class="text-negative-default text-xs">
              {validationMessage}
            </p>
          {/if}
        </div>

        <div class="flex min-w-0 flex-col gap-2">
          <Label for={minimumId}>
            {m.flow_classification_retention_minimum_label()}
          </Label>
          <InputGroup.Root>
            <InputGroup.Input
              id={minimumId}
              type="number"
              min={FLOW_CLASSIFICATION_RETENTION_MIN_DAYS}
              max={FLOW_CLASSIFICATION_RETENTION_MAX_DAYS}
              step="1"
              value={activeRow.draftMinimumDays}
              placeholder={m.flow_classification_retention_no_minimum()}
              aria-label={m.flow_classification_retention_minimum_input_label({
                name: activeRow.name
              })}
              aria-invalid={minimumValidationMessage ? true : undefined}
              aria-describedby={minimumValidationMessage ? minimumValidationMessageId : undefined}
              oninput={(event) => updateMinimumDraft(activeRow.id, event)}
            />
            <InputGroup.Addon align="inline-end">
              <InputGroup.Text>{m.flow_retention_days_suffix()}</InputGroup.Text>
            </InputGroup.Addon>
          </InputGroup.Root>
          <p class="text-secondary text-xs leading-relaxed">
            {m.flow_classification_retention_minimum_help()}
          </p>
          {#if minimumValidationMessage}
            <p id={minimumValidationMessageId} class="text-negative-default text-xs">
              {minimumValidationMessage}
            </p>
          {/if}
        </div>

        <div
          class="border-default flex items-start justify-between gap-6 border-y py-5 sm:col-span-2"
        >
          <div class="min-w-0">
            <Label for={noPurgeId}>{m.flow_classification_retention_pause_title()}</Label>
            <p class="text-secondary mt-1 text-xs leading-relaxed">
              {m.flow_classification_retention_pause_help()}
            </p>
          </div>
          <Switch
            id={noPurgeId}
            checked={activeRow.draftNoPurge}
            onCheckedChange={(checked) => updateNoPurgeDraft(activeRow.id, checked)}
            aria-label={`${m.flow_classification_retention_pause_title()}: ${activeRow.name}`}
          />
        </div>
      </div>

      <div
        class="bg-muted/50 border-default mt-1 flex flex-col-reverse gap-3 border-t px-6 py-4 sm:flex-row sm:items-center sm:justify-between"
      >
        <div class="flex w-full justify-start sm:w-auto">
          {#if activeRow.hasPolicy}
            <Button
              variant="ghost"
              class="text-negative-default hover:text-negative-default px-4"
              onclick={() => clearPolicy(activeRow)}
              disabled={savingById[activeRow.id] || clearingById[activeRow.id]}
            >
              {clearingById[activeRow.id]
                ? m.flow_classification_retention_clearing()
                : m.flow_classification_retention_clear_rule()}
            </Button>
          {/if}
        </div>
        <div class="flex w-full flex-col-reverse gap-2 sm:w-auto sm:flex-row">
          <Button variant="ghost" class="px-4" onclick={() => (editorOpen = false)}>
            {m.close()}
          </Button>
          {#if activeRow.hasChanges}
            <Button variant="outline" class="px-4" onclick={() => resetDraft(activeRow)}>
              {m.discard_changes()}
            </Button>
          {/if}
          <Button
            class="min-w-32 px-4"
            onclick={() => savePolicy(activeRow)}
            disabled={!canSave(activeRow)}
          >
            {savingById[activeRow.id] ? m.saving() : m.flow_settings_review_and_save()}
          </Button>
        </div>
      </div>
    {/if}
  </Dialog.Content>
</Dialog.Root>

{#if preview}
  <FlowRetentionImpactDialog
    bind:open={previewOpen}
    {preview}
    confirming={pendingRow ? Boolean(savingById[pendingRow.id]) : false}
    onConfirm={confirmPolicy}
  />
{/if}
