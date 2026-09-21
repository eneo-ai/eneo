<!-- Where the widget may run and what it may cost: origins, limits, privacy, protection. -->
<script lang="ts">
  import type { Widget, WidgetPolicy } from "@eneo/eneo-js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { m } from "$lib/paraglide/messages";
  import { untrack } from "svelte";
  import { blockerLabel } from "./blockers";
  import type { WidgetAutosave } from "./widgetAutosave.svelte";

  type Props = {
    autosave: WidgetAutosave;
    policy: WidgetPolicy | null;
  };

  let { autosave, policy }: Props = $props();

  const widget = $derived(autosave.widget);

  function limits(change: Partial<Widget["limits"]>) {
    autosave.patch({ limits: { ...widget.limits, ...change } });
  }
  function privacy(change: Partial<Widget["privacy"]>) {
    autosave.patch({ privacy: { ...widget.privacy, ...change } });
  }
  // Numbers are committed when the field is left, never per keystroke: a
  // half-typed budget must not reach the API as "2". Out-of-range values
  // stay in the field with an error instead of a failed save.
  let rangeErrors = $state<Record<string, string>>({});
  function commitNumber(
    event: Event,
    key: string,
    min: number,
    max: number,
    apply: (value: number) => void
  ) {
    const value = Number((event.currentTarget as HTMLInputElement).value);
    if (!Number.isInteger(value) || value < min || value > max) {
      rangeErrors = {
        ...rangeErrors,
        [key]: m.widget_admin_value_out_of_range({
          min: min.toLocaleString(),
          max: max.toLocaleString()
        })
      };
      return;
    }
    const { [key]: _cleared, ...rest } = rangeErrors;
    rangeErrors = rest;
    apply(value);
  }
  const describedBy = (key: string, help: string) =>
    rangeErrors[key] ? `${help} widget-${key}-error` : help;
  const budgetMax = $derived(policy?.max_daily_token_budget ?? 100_000_000);

  // Local text so a trailing newline is not eaten while typing.
  let originsText = $state(untrack(() => (autosave.widget.allowed_origins ?? []).join("\n")));
  const originsInvalid = $derived((widget.allowed_origins ?? []).length === 0);

  const protectionLabels = $derived({
    altcha: m.widget_admin_bot_protection_altcha(),
    none: m.widget_admin_bot_protection_none()
  });
  const noneAllowed = $derived(policy ? policy.allow_bot_protection_none : true);
</script>

<div class="grid gap-6">
  <Card.Root>
    <Card.Header>
      <Card.Title>{m.widget_admin_placement()}</Card.Title>
      <Card.Description>{m.widget_admin_allowed_origins_description()}</Card.Description>
    </Card.Header>
    <Card.Content>
      <Field.Field data-invalid={originsInvalid || undefined}>
        <Field.Label for="widget-origins">{m.widget_admin_allowed_origins()}</Field.Label>
        <Textarea
          id="widget-origins"
          rows={3}
          class="font-mono"
          placeholder={m.widget_admin_allowed_origins_placeholder()}
          aria-invalid={originsInvalid}
          aria-describedby={originsInvalid
            ? "widget-origins-help widget-origins-error"
            : "widget-origins-help"}
          bind:value={originsText}
          onchange={() =>
            autosave.patch({
              allowed_origins: originsText
                .split("\n")
                .map((line) => line.trim())
                .filter(Boolean)
            })}
        />
        <Field.Description id="widget-origins-help"
          >{m.widget_admin_allowed_origins_help()}</Field.Description
        >
        {#if originsInvalid}
          <Field.Error id="widget-origins-error"
            >{blockerLabel("allowed_origins_empty")}</Field.Error
          >
        {/if}
      </Field.Field>
    </Card.Content>
  </Card.Root>

  <Card.Root>
    <Card.Header>
      <Card.Title>{m.widget_admin_limits()}</Card.Title>
      <Card.Description>{m.widget_admin_limits_description()}</Card.Description>
    </Card.Header>
    <Card.Content>
      <Field.Group class="grid gap-6 sm:grid-cols-2">
        <Field.Field data-invalid={rangeErrors.budget ? true : undefined}>
          <Field.Label for="widget-budget">{m.widget_admin_daily_budget()}</Field.Label>
          <Input
            id="widget-budget"
            type="number"
            min={1000}
            step={1000}
            max={budgetMax}
            value={widget.limits.daily_token_budget}
            aria-invalid={!!rangeErrors.budget}
            aria-describedby={describedBy("budget", "widget-budget-help")}
            onchange={(event) =>
              commitNumber(event, "budget", 1000, budgetMax, (value) =>
                limits({ daily_token_budget: value })
              )}
          />
          {#if rangeErrors.budget}
            <Field.Error id="widget-budget-error">{rangeErrors.budget}</Field.Error>
          {/if}
          <Field.Description id="widget-budget-help">
            {policy
              ? m.widget_admin_daily_budget_description_policy({
                  max: policy.max_daily_token_budget.toLocaleString()
                })
              : m.widget_admin_daily_budget_description()}
          </Field.Description>
        </Field.Field>
        <Field.Field data-invalid={rangeErrors["ip-rate"] ? true : undefined}>
          <Field.Label for="widget-ip-rate">{m.widget_admin_messages_per_ip()}</Field.Label>
          <Input
            id="widget-ip-rate"
            type="number"
            min={1}
            max={1000}
            value={widget.limits.messages_per_ip_hour}
            aria-invalid={!!rangeErrors["ip-rate"]}
            aria-describedby={describedBy("ip-rate", "widget-ip-rate-help")}
            onchange={(event) =>
              commitNumber(event, "ip-rate", 1, 1000, (value) =>
                limits({ messages_per_ip_hour: value })
              )}
          />
          {#if rangeErrors["ip-rate"]}
            <Field.Error id="widget-ip-rate-error">{rangeErrors["ip-rate"]}</Field.Error>
          {/if}
          <Field.Description id="widget-ip-rate-help"
            >{m.widget_admin_messages_per_ip_description()}</Field.Description
          >
        </Field.Field>
        <Field.Field data-invalid={rangeErrors["question-chars"] ? true : undefined}>
          <Field.Label for="widget-question-chars"
            >{m.widget_admin_max_question_chars()}</Field.Label
          >
          <Input
            id="widget-question-chars"
            type="number"
            min={100}
            max={8000}
            step={100}
            value={widget.limits.max_question_chars}
            aria-invalid={!!rangeErrors["question-chars"]}
            aria-describedby={describedBy("question-chars", "widget-question-chars-help")}
            onchange={(event) =>
              commitNumber(event, "question-chars", 100, 8000, (value) =>
                limits({ max_question_chars: value })
              )}
          />
          {#if rangeErrors["question-chars"]}
            <Field.Error id="widget-question-chars-error"
              >{rangeErrors["question-chars"]}</Field.Error
            >
          {/if}
          <Field.Description id="widget-question-chars-help"
            >{m.widget_admin_max_question_chars_description()}</Field.Description
          >
        </Field.Field>
        <Field.Field data-invalid={rangeErrors.turns ? true : undefined}>
          <Field.Label for="widget-turns">{m.widget_admin_max_turns()}</Field.Label>
          <Input
            id="widget-turns"
            type="number"
            min={1}
            max={100}
            value={widget.limits.max_session_turns}
            aria-invalid={!!rangeErrors.turns}
            aria-describedby={describedBy("turns", "widget-turns-help")}
            onchange={(event) =>
              commitNumber(event, "turns", 1, 100, (value) => limits({ max_session_turns: value }))}
          />
          {#if rangeErrors.turns}
            <Field.Error id="widget-turns-error">{rangeErrors.turns}</Field.Error>
          {/if}
          <Field.Description id="widget-turns-help"
            >{m.widget_admin_max_turns_description()}</Field.Description
          >
        </Field.Field>
      </Field.Group>
    </Card.Content>
  </Card.Root>

  <Card.Root>
    <Card.Header>
      <Card.Title>{m.widget_admin_privacy()}</Card.Title>
      <Card.Description>{m.widget_admin_privacy_description()}</Card.Description>
    </Card.Header>
    <Card.Content>
      <Field.Group class="grid gap-6">
        <Field.Field data-invalid={rangeErrors.retention ? true : undefined}>
          <Field.Label for="widget-retention">{m.widget_admin_retention()}</Field.Label>
          <Input
            id="widget-retention"
            type="number"
            class="max-w-40"
            min={policy?.min_retention_days ?? 0}
            max={policy?.max_retention_days ?? 3650}
            value={widget.privacy.retention_days}
            aria-invalid={!!rangeErrors.retention}
            aria-describedby={describedBy("retention", "widget-retention-help")}
            onchange={(event) =>
              commitNumber(
                event,
                "retention",
                policy?.min_retention_days ?? 0,
                policy?.max_retention_days ?? 3650,
                (value) => privacy({ retention_days: value })
              )}
          />
          {#if rangeErrors.retention}
            <Field.Error id="widget-retention-error">{rangeErrors.retention}</Field.Error>
          {/if}
          <Field.Description id="widget-retention-help">
            {policy
              ? m.widget_admin_retention_description_policy({
                  min: String(policy.min_retention_days),
                  max: String(policy.max_retention_days)
                })
              : m.widget_admin_retention_description()}
          </Field.Description>
        </Field.Field>
        <Field.Field orientation="horizontal">
          <Field.Content>
            <Field.Label for="widget-feedback-text"
              >{m.widget_admin_store_feedback_text()}</Field.Label
            >
            <Field.Description>{m.widget_admin_store_feedback_text_description()}</Field.Description
            >
          </Field.Content>
          <Switch
            id="widget-feedback-text"
            checked={widget.privacy.store_feedback_text ?? false}
            onCheckedChange={(checked) => privacy({ store_feedback_text: checked })}
          />
        </Field.Field>
      </Field.Group>
    </Card.Content>
  </Card.Root>

  <Card.Root>
    <Card.Header>
      <Card.Title>{m.widget_admin_protection()}</Card.Title>
      <Card.Description>{m.widget_admin_bot_protection_description()}</Card.Description>
    </Card.Header>
    <Card.Content>
      <Field.Field>
        <Field.Label for="widget-protection">{m.widget_admin_bot_protection()}</Field.Label>
        <Select.Root
          type="single"
          value={widget.bot_protection ?? "altcha"}
          onValueChange={(value) =>
            autosave.patch({ bot_protection: value as NonNullable<Widget["bot_protection"]> })}
        >
          <Select.Trigger id="widget-protection" class="w-full sm:max-w-md">
            <span data-slot="select-value"
              >{protectionLabels[widget.bot_protection ?? "altcha"]}</span
            >
          </Select.Trigger>
          <Select.Content>
            <Select.Item value="altcha" label={protectionLabels.altcha}
              >{protectionLabels.altcha}</Select.Item
            >
            <Select.Item value="none" label={protectionLabels.none} disabled={!noneAllowed}
              >{protectionLabels.none}</Select.Item
            >
          </Select.Content>
        </Select.Root>
        {#if !noneAllowed}
          <Field.Description>{m.widget_admin_blocker_bot_protection()}</Field.Description>
        {/if}
      </Field.Field>
    </Card.Content>
  </Card.Root>
</div>
