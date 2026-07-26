<script lang="ts">
  import type {
    SkillRuntimeModelProjections,
    SkillRuntimePolicy,
    SkillRuntimePolicyUpdate
  } from "@eneo/eneo-js";
  import { useId } from "bits-ui";
  import { CircleAlert, RotateCcw } from "lucide-svelte";
  import { untrack } from "svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { m } from "$lib/paraglide/messages";
  import {
    isSkillRuntimePolicyDraftValid,
    isSkillRuntimePolicyFieldValid,
    skillRuntimePolicyDraft,
    skillRuntimePolicyDraftEquals,
    type SkillRuntimePolicyDraft,
    type SkillRuntimePolicySnapshot
  } from "./skillRuntimePolicy";

  type Props = {
    initialPolicy: SkillRuntimePolicy;
    initialModelProjections: SkillRuntimeModelProjections | null;
    onSave: (policy: SkillRuntimePolicyUpdate) => Promise<SkillRuntimePolicySnapshot>;
    onReset: () => Promise<SkillRuntimePolicySnapshot>;
  };

  let { initialPolicy, initialModelProjections, onSave, onReset }: Props = $props();

  const id = useId();
  const fieldIds = {
    selective: `${id}-selective`,
    attached: `${id}-attached`,
    context: `${id}-context`,
    activations: `${id}-activations`,
    models: `${id}-models`
  };

  let policy = $state(untrack(() => initialPolicy));
  let modelProjections = $state<SkillRuntimeModelProjections | null>(
    untrack(() => initialModelProjections)
  );
  let draft = $state<SkillRuntimePolicyDraft>(
    untrack(() => skillRuntimePolicyDraft(initialPolicy))
  );
  let busy = $state<"save" | "reset" | null>(null);
  let resetOpen = $state(false);
  let errorMessage = $state<string | null>(null);
  let statusMessage = $state<string | null>(null);

  const valid = $derived(isSkillRuntimePolicyDraftValid(draft, policy.editable_bounds));
  const dirty = $derived(!skillRuntimePolicyDraftEquals(draft, skillRuntimePolicyDraft(policy)));

  function applySnapshot(snapshot: SkillRuntimePolicySnapshot) {
    policy = snapshot.policy;
    modelProjections = snapshot.modelProjections;
    draft = skillRuntimePolicyDraft(snapshot.policy);
  }

  async function save() {
    // Revalidate here so the nullable draft narrows to the generated update contract.
    if (busy !== null || !dirty || !isSkillRuntimePolicyDraftValid(draft, policy.editable_bounds))
      return;
    const payload: SkillRuntimePolicyUpdate = { ...draft };
    busy = "save";
    errorMessage = null;
    statusMessage = null;
    try {
      applySnapshot(await onSave(payload));
      statusMessage = m.skills_runtime_policy_saved();
    } catch {
      errorMessage = m.skills_runtime_policy_save_error();
    } finally {
      busy = null;
    }
  }

  async function reset() {
    if (busy !== null) return;
    busy = "reset";
    errorMessage = null;
    statusMessage = null;
    try {
      applySnapshot(await onReset());
      statusMessage = m.skills_runtime_policy_reset_done();
    } catch {
      errorMessage = m.skills_runtime_policy_reset_error();
    } finally {
      busy = null;
    }
  }
</script>

<div class="flex flex-col gap-6">
  <Field.Set class="gap-5">
    <Field.Field orientation="horizontal">
      <Field.Content>
        <Field.Title>{m.skills_runtime_policy_selective_title()}</Field.Title>
        <Field.Description>{m.skills_runtime_policy_selective_description()}</Field.Description>
      </Field.Content>
      <Switch
        id={fieldIds.selective}
        aria-label={m.skills_runtime_policy_selective_title()}
        bind:checked={draft.selective_activation_enabled}
        disabled={busy !== null}
      />
    </Field.Field>

    <Field.Separator />

    <Field.Group class="grid gap-5 md:grid-cols-3">
      <Field.Field>
        <Field.Label for={fieldIds.attached}>{m.skills_runtime_policy_max_attached()}</Field.Label>
        <Input
          id={fieldIds.attached}
          type="number"
          step="1"
          min={policy.editable_bounds.max_attached_skills.minimum}
          max={policy.editable_bounds.max_attached_skills.maximum}
          bind:value={draft.max_attached_skills}
          aria-invalid={!isSkillRuntimePolicyFieldValid(
            draft.max_attached_skills,
            policy.editable_bounds.max_attached_skills
          )}
          disabled={busy !== null}
        />
        <Field.Description>{m.skills_runtime_policy_max_attached_description()}</Field.Description>
        <Field.Description class="text-xs tabular-nums">
          {m.skills_runtime_policy_allowed_range({
            minimum: String(policy.editable_bounds.max_attached_skills.minimum),
            maximum: String(policy.editable_bounds.max_attached_skills.maximum)
          })}
        </Field.Description>
      </Field.Field>

      <Field.Field>
        <Field.Label for={fieldIds.context}>{m.skills_runtime_policy_context_share()}</Field.Label>
        <Input
          id={fieldIds.context}
          type="number"
          step="1"
          min={policy.editable_bounds.context_share_percent.minimum}
          max={policy.editable_bounds.context_share_percent.maximum}
          bind:value={draft.context_share_percent}
          aria-invalid={!isSkillRuntimePolicyFieldValid(
            draft.context_share_percent,
            policy.editable_bounds.context_share_percent
          )}
          disabled={busy !== null}
        />
        <Field.Description>{m.skills_runtime_policy_context_share_description()}</Field.Description>
        <Field.Description class="text-xs tabular-nums">
          {m.skills_runtime_policy_allowed_range({
            minimum: String(policy.editable_bounds.context_share_percent.minimum),
            maximum: String(policy.editable_bounds.context_share_percent.maximum)
          })}
        </Field.Description>
      </Field.Field>

      <Field.Field>
        <Field.Label for={fieldIds.activations}>
          {m.skills_runtime_policy_max_activations()}
        </Field.Label>
        <Input
          id={fieldIds.activations}
          type="number"
          step="1"
          min={policy.editable_bounds.max_activations_per_turn.minimum}
          max={policy.editable_bounds.max_activations_per_turn.maximum}
          bind:value={draft.max_activations_per_turn}
          aria-invalid={!isSkillRuntimePolicyFieldValid(
            draft.max_activations_per_turn,
            policy.editable_bounds.max_activations_per_turn
          )}
          disabled={busy !== null}
        />
        <Field.Description
          >{m.skills_runtime_policy_max_activations_description()}</Field.Description
        >
        <Field.Description class="text-xs tabular-nums">
          {m.skills_runtime_policy_allowed_range({
            minimum: String(policy.editable_bounds.max_activations_per_turn.minimum),
            maximum: String(policy.editable_bounds.max_activations_per_turn.maximum)
          })}
        </Field.Description>
      </Field.Field>
    </Field.Group>
  </Field.Set>

  {#if !valid}
    <p class="text-destructive text-sm" role="alert">{m.skills_runtime_policy_invalid()}</p>
  {/if}

  {#if errorMessage}
    <Alert.Root variant="destructive">
      <CircleAlert aria-hidden="true" />
      <Alert.Title>{errorMessage}</Alert.Title>
    </Alert.Root>
  {/if}

  <div class="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
    <p class="text-muted-foreground min-h-5 text-sm" role="status" aria-live="polite">
      {statusMessage ?? ""}
    </p>
    <div class="flex flex-wrap justify-end gap-2">
      <Button
        type="button"
        variant="outline"
        disabled={busy !== null}
        onclick={() => (resetOpen = true)}
      >
        <RotateCcw data-icon="inline-start" aria-hidden="true" />
        {m.skills_runtime_policy_reset()}
      </Button>
      <Button
        type="button"
        disabled={busy !== null || !dirty || !valid}
        onclick={() => void save()}
      >
        {busy === "save" ? m.skills_runtime_policy_saving() : m.skills_runtime_policy_save()}
      </Button>
    </div>
  </div>

  <section class="border-t pt-5" aria-labelledby={fieldIds.models}>
    <h4 id={fieldIds.models} class="text-base font-medium">{m.skills_runtime_models_title()}</h4>

    {#if modelProjections === null}
      <Alert.Root class="mt-4">
        <CircleAlert aria-hidden="true" />
        <Alert.Title>{m.skills_runtime_models_unavailable_title()}</Alert.Title>
        <Alert.Description>{m.skills_runtime_models_unavailable_description()}</Alert.Description>
      </Alert.Root>
    {:else if modelProjections.models.length === 0}
      <p class="text-muted-foreground mt-4 text-sm">{m.skills_runtime_models_empty()}</p>
    {:else}
      <p class="text-muted-foreground mt-1 max-w-[75ch] text-sm leading-6">
        {m.skills_runtime_models_description({
          percent: String(policy.context_share_percent)
        })}
      </p>
      <!-- svelte-ignore a11y_no_noninteractive_tabindex (bounded table must be keyboard-scrollable) -->
      <div
        class="border-border focus-visible:ring-ring mt-4 max-h-72 overflow-y-auto border-y outline-none focus-visible:ring-2 [scrollbar-gutter:stable]"
        role="region"
        aria-label={m.skills_runtime_models_region({
          count: String(modelProjections.models.length)
        })}
        tabindex="0"
      >
        <Table.Root>
          <Table.Header class="bg-background sticky top-0 z-[1]">
            <Table.Row>
              <Table.Head>{m.skills_runtime_models_model()}</Table.Head>
              <Table.Head class="text-right">{m.skills_runtime_models_input_window()}</Table.Head>
              <Table.Head class="text-right">{m.skills_runtime_models_skill_budget()}</Table.Head>
              <Table.Head>{m.skills_runtime_models_tool_calling()}</Table.Head>
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {#each modelProjections.models as model (model.completion_model_id)}
              <Table.Row>
                <Table.Cell class="min-w-48">
                  <span class="block font-medium">{model.nickname ?? model.name}</span>
                  {#if model.nickname}
                    <span class="text-muted-foreground block max-w-72 truncate text-xs">
                      {model.name}
                    </span>
                  {/if}
                </Table.Cell>
                <Table.Cell class="text-right tabular-nums">
                  {m.skills_runtime_tokens({ count: model.max_input_tokens.toLocaleString() })}
                </Table.Cell>
                <Table.Cell class="text-right tabular-nums">
                  {m.skills_runtime_tokens({
                    count: model.skill_context_token_allowance.toLocaleString()
                  })}
                </Table.Cell>
                <Table.Cell>
                  <Badge variant={model.supports_tool_calling ? "secondary" : "outline"}>
                    {model.supports_tool_calling
                      ? m.skills_runtime_models_supported()
                      : m.skills_runtime_models_not_supported()}
                  </Badge>
                </Table.Cell>
              </Table.Row>
            {/each}
          </Table.Body>
        </Table.Root>
      </div>
    {/if}
  </section>
</div>

<AlertDialog.Root bind:open={resetOpen}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.skills_runtime_policy_reset_title()}</AlertDialog.Title>
      <AlertDialog.Description
        >{m.skills_runtime_policy_reset_description()}</AlertDialog.Description
      >
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action onclick={() => void reset()}>
        {m.skills_runtime_policy_reset()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
