<script lang="ts">
  import type { FlowRetentionImpactPreview } from "@eneo/eneo-js";
  import AlertTriangle from "lucide-svelte/icons/alert-triangle";
  import CircleCheck from "lucide-svelte/icons/circle-check";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import { formatFlowRetentionBytes } from "../flowRetentionPolicy";

  let {
    preview,
    open = $bindable(false),
    confirming = false,
    onConfirm
  }: {
    preview: FlowRetentionImpactPreview;
    open?: boolean;
    confirming?: boolean;
    onConfirm: () => void;
  } = $props();

  let acknowledged = $state(false);

  $effect(() => {
    if (open) acknowledged = false;
  });

  function formatAnchor(value: string | null | undefined): string {
    if (!value) return m.flow_retention_preview_no_anchor();
    return new Date(value).toLocaleString(getLocale());
  }

  function anchorFieldLabel(field: string): string {
    switch (field) {
      case "finished_at_or_created_at":
        return m.flow_retention_anchor_finished_at_or_created_at();
      case "created_at":
        return m.flow_retention_anchor_created_at();
      default:
        return field;
    }
  }

  const hasImpact = $derived.by(() => {
    const sections = [preview.run_history, preview.runtime_uploads];
    return sections.some(
      (section) =>
        section.current_eligible_count > 0 ||
        section.proposed_eligible_count > 0 ||
        section.newly_eligible_count > 0 ||
        section.no_longer_eligible_count > 0
    );
  });
</script>

<Dialog.Root bind:open>
  <Dialog.Content class="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
    <Dialog.Header>
      <Dialog.Title>{m.flow_retention_preview_title()}</Dialog.Title>
      <Dialog.Description>{m.flow_retention_preview_description()}</Dialog.Description>
    </Dialog.Header>

    {#if !hasImpact}
      <Alert.Root>
        <CircleCheck aria-hidden="true" />
        <Alert.Description>{m.flow_retention_preview_no_impact()}</Alert.Description>
      </Alert.Root>
    {/if}

    <div class="grid gap-3 sm:grid-cols-2" class:hidden={!hasImpact}>
      <section class="border-default rounded-lg border p-4">
        <h3 class="text-primary font-semibold">{m.flow_retention_run_history_title()}</h3>
        <p class="text-secondary mt-1 text-xs">
          {m.flow_retention_preview_anchor_field({
            field: anchorFieldLabel(preview.run_history_anchor)
          })}
        </p>
        <dl class="mt-3 grid grid-cols-2 gap-3 text-sm">
          <div>
            <dt class="text-secondary">{m.flow_retention_preview_current_eligible()}</dt>
            <dd class="text-primary mt-1 font-semibold">
              {preview.run_history.current_eligible_count}
            </dd>
          </div>
          <div>
            <dt class="text-secondary">{m.flow_retention_preview_proposed_eligible()}</dt>
            <dd class="text-primary mt-1 font-semibold">
              {preview.run_history.proposed_eligible_count}
            </dd>
          </div>
          <div>
            <dt class="text-secondary">{m.flow_retention_preview_newly_eligible()}</dt>
            <dd class="text-primary mt-1 font-semibold">
              {preview.run_history.newly_eligible_count}
            </dd>
          </div>
          <div>
            <dt class="text-secondary">{m.flow_retention_preview_no_longer_eligible()}</dt>
            <dd class="text-primary mt-1 font-semibold">
              {preview.run_history.no_longer_eligible_count}
            </dd>
          </div>
          <div>
            <dt class="text-secondary">{m.flow_retention_preview_bytes()}</dt>
            <dd class="text-primary mt-1 font-semibold">
              {formatFlowRetentionBytes(preview.run_history.newly_eligible_bytes)}
            </dd>
          </div>
          <div class="col-span-2">
            <dt class="text-secondary">{m.flow_retention_preview_anchor()}</dt>
            <dd class="text-primary mt-1">
              {formatAnchor(preview.run_history.earliest_proposed_anchor)} –
              {formatAnchor(preview.run_history.latest_proposed_anchor)}
            </dd>
          </div>
          <div class="col-span-2">
            <dt class="text-secondary">{m.flow_retention_preview_delete_after_range()}</dt>
            <dd class="text-primary mt-1">
              {formatAnchor(preview.run_history.earliest_proposed_delete_after_at)} –
              {formatAnchor(preview.run_history.latest_proposed_delete_after_at)}
            </dd>
          </div>
          <div class="col-span-2">
            <dt class="text-secondary">{m.flow_retention_preview_minimum_range()}</dt>
            <dd class="text-primary mt-1">
              {formatAnchor(preview.run_history.earliest_proposed_minimum_not_before_at)} –
              {formatAnchor(preview.run_history.latest_proposed_minimum_not_before_at)}
            </dd>
          </div>
        </dl>
      </section>

      <section class="border-default rounded-lg border p-4">
        <h3 class="text-primary font-semibold">{m.flow_retention_upload_title()}</h3>
        <p class="text-secondary mt-1 text-xs">
          {m.flow_retention_preview_anchor_field({
            field: anchorFieldLabel(preview.runtime_upload_anchor)
          })}
        </p>
        <dl class="mt-3 grid grid-cols-2 gap-3 text-sm">
          <div>
            <dt class="text-secondary">{m.flow_retention_preview_current_eligible()}</dt>
            <dd class="text-primary mt-1 font-semibold">
              {preview.runtime_uploads.current_eligible_count}
            </dd>
          </div>
          <div>
            <dt class="text-secondary">{m.flow_retention_preview_proposed_eligible()}</dt>
            <dd class="text-primary mt-1 font-semibold">
              {preview.runtime_uploads.proposed_eligible_count}
            </dd>
          </div>
          <div>
            <dt class="text-secondary">{m.flow_retention_preview_newly_eligible()}</dt>
            <dd class="text-primary mt-1 font-semibold">
              {preview.runtime_uploads.newly_eligible_count}
            </dd>
          </div>
          <div>
            <dt class="text-secondary">{m.flow_retention_preview_no_longer_eligible()}</dt>
            <dd class="text-primary mt-1 font-semibold">
              {preview.runtime_uploads.no_longer_eligible_count}
            </dd>
          </div>
          <div>
            <dt class="text-secondary">{m.flow_retention_preview_bytes()}</dt>
            <dd class="text-primary mt-1 font-semibold">
              {formatFlowRetentionBytes(preview.runtime_uploads.newly_eligible_bytes)}
            </dd>
          </div>
          <div class="col-span-2">
            <dt class="text-secondary">{m.flow_retention_preview_anchor()}</dt>
            <dd class="text-primary mt-1">
              {formatAnchor(preview.runtime_uploads.earliest_proposed_anchor)} –
              {formatAnchor(preview.runtime_uploads.latest_proposed_anchor)}
            </dd>
          </div>
          <div class="col-span-2">
            <dt class="text-secondary">{m.flow_retention_preview_delete_after_range()}</dt>
            <dd class="text-primary mt-1">
              {formatAnchor(preview.runtime_uploads.earliest_proposed_delete_after_at)} –
              {formatAnchor(preview.runtime_uploads.latest_proposed_delete_after_at)}
            </dd>
          </div>
          <div class="col-span-2">
            <dt class="text-secondary">{m.flow_retention_preview_minimum_range()}</dt>
            <dd class="text-primary mt-1">
              {formatAnchor(preview.runtime_uploads.earliest_proposed_minimum_not_before_at)} –
              {formatAnchor(preview.runtime_uploads.latest_proposed_minimum_not_before_at)}
            </dd>
          </div>
        </dl>
      </section>
    </div>

    <section
      class="bg-secondary border-default rounded-lg border p-4 text-sm"
      class:hidden={!hasImpact}
    >
      <h3 class="text-primary font-semibold">{m.flow_retention_preview_blockers_title()}</h3>
      <ul class="text-secondary mt-2 grid gap-1 sm:grid-cols-3">
        <li>
          {m.flow_retention_preview_undelivered_audit()}:
          {preview.lifecycle_blockers.undelivered_audit_count}
        </li>
        <li>
          {m.flow_retention_preview_unresolved_webhook()}:
          {preview.lifecycle_blockers.unresolved_webhook_count}
        </li>
        <li>
          {m.flow_retention_preview_active_rerun()}:
          {preview.lifecycle_blockers.active_rerun_count}
        </li>
      </ul>
      <h4 class="text-primary mt-3 font-medium">{m.flow_retention_preview_policy_blockers()}</h4>
      <ul class="text-secondary mt-2 grid gap-1 sm:grid-cols-3">
        <li>
          {m.flow_retention_preview_minimum_blocked()}:
          {preview.policy_blockers.run_history_minimum_not_satisfied_count}
        </li>
        <li>
          {m.flow_retention_preview_no_purge_blocked()}:
          {preview.policy_blockers.run_history_no_purge_count}
        </li>
        <li>
          {m.flow_retention_preview_conflicts()}:
          {preview.policy_blockers.run_history_policy_conflict_count}
        </li>
      </ul>
      <p class="text-secondary mt-3">
        {m.flow_retention_preview_latent_values({
          spaces: preview.latent_space_retention_days.join(", ") || "–",
          flows: preview.latent_flow_retention_days.join(", ") || "–"
        })}
      </p>
    </section>

    <div class="border-warning-default bg-warning-dimmer flex gap-3 rounded-lg border p-4">
      <AlertTriangle class="text-warning-default mt-0.5 size-5 shrink-0" />
      <div>
        <p class="text-primary text-sm font-semibold">
          {m.flow_retention_preservation_title()}
        </p>
        <p class="text-primary mt-1 text-sm leading-relaxed">
          {m.flow_retention_preservation_hold_caveat()}
        </p>
      </div>
    </div>

    <div class="flex items-start gap-3">
      <Checkbox id="flow-retention-acknowledge" bind:checked={acknowledged} class="mt-0.5" />
      <Label for="flow-retention-acknowledge" class="text-primary text-sm leading-snug font-normal">
        {m.flow_retention_preview_acknowledgement()}
      </Label>
    </div>

    <Dialog.Footer>
      <Dialog.Close>
        {#snippet child({ props })}
          <Button variant="outline" {...props}>{m.cancel()}</Button>
        {/snippet}
      </Dialog.Close>
      <Button onclick={onConfirm} disabled={!acknowledged || confirming}>
        {confirming ? m.saving() : m.flow_retention_preview_confirm()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
