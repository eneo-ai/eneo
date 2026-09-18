<script lang="ts">
  import type {
    FlowRunRetentionMode,
    FlowRunRetentionPolicy,
    FlowRunRetentionPolicySettings
  } from "@eneo/eneo-js";
  import { untrack } from "svelte";

  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { toast } from "$lib/components/toast";
  import { toastError } from "$lib/core/errors";
  import {
    FLOW_RETENTION_MAX_DAYS,
    FLOW_RETENTION_MIN_DAYS,
    flowRunRetentionPoliciesEqual,
    parseFlowRunRetentionDays
  } from "$lib/features/flows/flowRunRetentionPolicy";
  import { m } from "$lib/paraglide/messages";

  type PolicyChoice = "none" | FlowRunRetentionMode;

  type Props = {
    settings: FlowRunRetentionPolicySettings;
    title: string;
    description: string;
    onSave: (policy: FlowRunRetentionPolicy | null) => Promise<FlowRunRetentionPolicySettings>;
    onDirtyChange?: (dirty: boolean) => void;
  };

  let { settings, title, description, onSave, onDirtyChange }: Props = $props();
  const initialPolicy = untrack(() => settings.local_policy);
  const fallbackDays = untrack(() => initialPolicy?.days ?? settings.inherited_policy?.days ?? 365);

  let savedPolicy = $state<FlowRunRetentionPolicy | null>(initialPolicy);
  let choice = $state<PolicyChoice>(initialPolicy?.mode ?? "none");
  let daysInput = $state<string | number>(String(fallbackDays));
  let saving = $state(false);

  const parsedDays = $derived(parseFlowRunRetentionDays(daysInput));
  const valid = $derived(choice === "none" || parsedDays !== null);
  const proposedPolicy = $derived<FlowRunRetentionPolicy | null>(
    choice === "none" || parsedDays === null ? null : { mode: choice, days: parsedDays }
  );
  const dirty = $derived(
    valid ? !flowRunRetentionPoliciesEqual(savedPolicy, proposedPolicy) : choice !== "none"
  );

  $effect(() => {
    onDirtyChange?.(dirty);
    return () => onDirtyChange?.(false);
  });

  function scopeLabel(): string {
    return definiteScopeLabel(settings.scope);
  }

  // Every template these feed puts the noun after a preposition ("för …",
  // "från …"), which Swedish renders in the definite form; the bare nouns are
  // for headings and column titles.
  function definiteScopeLabel(scope: "organization" | "space" | "flow"): string {
    if (scope === "organization") return m.flow_run_retention_scope_organization_definite();
    if (scope === "space") return m.flow_run_retention_scope_space_definite();
    return m.flow_run_retention_scope_flow_definite();
  }

  function sourceLabel(source: "organization" | "space" | "flow"): string {
    return definiteScopeLabel(source);
  }

  function choiceLabel(value: PolicyChoice): string {
    if (value === "none") {
      return settings.scope === "organization"
        ? m.flow_run_retention_choice_no_policy()
        : m.flow_run_retention_choice_inherit();
    }
    return value === "preserve"
      ? m.flow_run_retention_mode_preserve()
      : m.flow_run_retention_mode_review();
  }

  function modeDescription(value: PolicyChoice): string {
    if (value === "none") {
      return settings.scope === "organization"
        ? m.flow_run_retention_no_policy_description()
        : m.flow_run_retention_inherit_description();
    }
    return value === "preserve"
      ? m.flow_run_retention_mode_preserve_description()
      : m.flow_run_retention_mode_review_description();
  }

  const LEVELS = ["organization", "space", "flow"] as const;

  /**
   * The card already resolves inheritance into one badge; this says how it got
   * there. `contributors` is computed server-side and was not shown anywhere,
   * so the three levels were only ever described in prose — four times over on
   * this tab. Levels below the card's own scope are not its business.
   */
  const chain = $derived.by(() => {
    const upto = LEVELS.indexOf(settings.scope) + 1;
    return LEVELS.slice(0, upto).map((level) => {
      const own = settings.effective.contributors?.[level] ?? null;
      return {
        level,
        name: bareScopeLabel(level),
        value: own ? `${own.days} ${m.flow_retention_days_suffix()}` : null,
        wins: settings.effective.state !== "off" && settings.effective.source === level
      };
    });
  });

  function bareScopeLabel(scope: "organization" | "space" | "flow"): string {
    if (scope === "organization") return m.flow_run_retention_scope_organization();
    if (scope === "space") return m.flow_run_retention_scope_space();
    return m.flow_run_retention_scope_flow();
  }

  function effectiveSummary(): string {
    if (settings.effective.state === "off") {
      return m.flow_run_retention_effective_off();
    }
    return m.flow_run_retention_effective_configured({
      days: settings.effective.effective_days,
      mode: choiceLabel(settings.effective.mode),
      source: sourceLabel(settings.effective.source)
    });
  }

  async function save(): Promise<void> {
    if (!dirty || !valid || saving) return;
    saving = true;
    try {
      const updated = await onSave(proposedPolicy);
      settings = updated;
      savedPolicy = updated.local_policy;
      choice = updated.local_policy?.mode ?? "none";
      daysInput = String(
        updated.local_policy?.days ?? updated.inherited_policy?.days ?? parsedDays ?? 365
      );
      toast.success(m.saved_successfully());
    } catch (error) {
      toastError(error);
    } finally {
      saving = false;
    }
  }
</script>

<Card.Root size="sm" class="mx-4 w-auto gap-4 lg:mx-0.5">
  <Card.Header class="gap-1.5">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0">
        <Card.Title class="text-base">{title}</Card.Title>
        <Card.Description class="mt-1 max-w-3xl leading-relaxed">{description}</Card.Description>
      </div>
      <Badge variant="secondary">{effectiveSummary()}</Badge>
    </div>
  </Card.Header>
  <!--
    The two fields start on the same line so their labels and controls align;
    bottom-aligning them instead staggered the labels, because the help text
    under each one is a different number of lines.
  -->
  <Card.Content class="grid gap-x-6 gap-y-4 md:grid-cols-[minmax(0,1fr)_12rem] md:items-start">
    <Field.Field>
      <Field.Label for={`flow-retention-mode-${settings.scope}`}>
        {m.flow_run_retention_behavior_label()}
      </Field.Label>
      <Select.Root type="single" bind:value={choice} disabled={saving}>
        <Select.Trigger
          id={`flow-retention-mode-${settings.scope}`}
          class="w-full"
          aria-label={m.flow_run_retention_behavior_for_scope({ scope: scopeLabel() })}
        >
          <span class="truncate">{choiceLabel(choice)}</span>
        </Select.Trigger>
        <Select.Content>
          <Select.Item value="none" label={choiceLabel("none")}>{choiceLabel("none")}</Select.Item>
          <Select.Item value="preserve" label={choiceLabel("preserve")}>
            {choiceLabel("preserve")}
          </Select.Item>
          <Select.Item value="review_required" label={choiceLabel("review_required")}>
            {choiceLabel("review_required")}
          </Select.Item>
        </Select.Content>
      </Select.Root>
      <Field.Description>{modeDescription(choice)}</Field.Description>
    </Field.Field>

    <Field.Field data-invalid={!valid || undefined}>
      <Field.Label for={`flow-retention-days-${settings.scope}`}>
        {m.flow_run_retention_days_label()}
      </Field.Label>
      <div class="flex items-center gap-2">
        <Input
          id={`flow-retention-days-${settings.scope}`}
          class="tabular-nums"
          type="number"
          min={FLOW_RETENTION_MIN_DAYS}
          max={FLOW_RETENTION_MAX_DAYS}
          step="1"
          bind:value={daysInput}
          disabled={choice === "none" || saving}
          aria-invalid={!valid}
          aria-describedby={`flow-retention-days-help-${settings.scope}`}
        />
        <span class="text-secondary text-sm">{m.flow_retention_days_suffix()}</span>
      </div>
      <Field.Description id={`flow-retention-days-help-${settings.scope}`}>
        {valid
          ? m.flow_run_retention_days_description()
          : m.flow_run_retention_days_error({
              min: FLOW_RETENTION_MIN_DAYS,
              max: FLOW_RETENTION_MAX_DAYS
            })}
      </Field.Description>
    </Field.Field>
    {#if chain.length > 1}
      <div class="col-span-full">
        <p class="text-secondary text-xs font-medium">{m.flow_run_retention_chain_title()}</p>
        <ol class="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs">
          {#each chain as step, i (step.level)}
            {#if i > 0}
              <li aria-hidden="true" class="text-muted">›</li>
            {/if}
            <li class={step.wins ? "text-primary font-medium" : "text-secondary"}>
              {step.name}
              <span class="text-muted">
                {step.value ?? m.flow_run_retention_level_inherits()}
              </span>
              {#if step.wins}
                <span class="text-muted">· {m.flow_run_retention_level_applies()}</span>
              {/if}
            </li>
          {/each}
        </ol>
      </div>
    {/if}
  </Card.Content>
  <!--
    Committing a retention policy is the card's one action, and its label carries
    the scope, so it needs a full row rather than a grid cell sized to whatever
    the scope noun happens to be in this locale.
  -->
  <Card.Footer class="border-default justify-between gap-3">
    <p class="text-secondary text-xs">
      {#if !dirty}{m.flow_run_retention_no_changes()}{/if}
    </p>
    <Button type="button" disabled={!dirty || !valid || saving} onclick={save}>
      {saving
        ? m.flow_run_retention_saving()
        : m.flow_run_retention_save_scope({ scope: scopeLabel() })}
    </Button>
  </Card.Footer>
</Card.Root>
