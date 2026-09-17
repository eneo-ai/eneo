<!--
  Everything an editor configures on a widget. Each field patches the
  autosave immediately; nested groups are sent whole because the API replaces
  them as units.
-->
<script lang="ts">
  import type { WidgetPolicy, WidgetTemplate } from "@eneo/eneo-js";
  import { Button, Input } from "@eneo/ui";
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import { untrack } from "svelte";
  import { inputClass, textareaClass } from "./fieldStyles";
  import type { WidgetAutosave } from "./widgetAutosave.svelte";
  import WidgetTextsFields from "./WidgetTextsFields.svelte";
  import WidgetThemeFields from "./WidgetThemeFields.svelte";

  type Props = {
    autosave: WidgetAutosave;
    policy: WidgetPolicy | null;
    assistantPublished: boolean;
    templates: WidgetTemplate[];
    onApplyTemplate: (templateId: string) => Promise<void>;
  };

  let { autosave, policy, assistantPublished, templates, onApplyTemplate }: Props = $props();

  const widget = $derived(autosave.widget);

  let selectedTemplate = $state("");
  let applying = $state(false);

  async function applyTemplate() {
    if (!selectedTemplate) return;
    applying = true;
    try {
      await onApplyTemplate(selectedTemplate);
    } finally {
      applying = false;
    }
  }

  function texts(change: Partial<typeof widget.texts>) {
    autosave.patch({ texts: { ...widget.texts, ...change } });
  }
  function theme(change: Partial<typeof widget.theme>) {
    autosave.patch({ theme: { ...widget.theme, ...change } });
  }
  function limits(change: Partial<typeof widget.limits>) {
    autosave.patch({ limits: { ...widget.limits, ...change } });
  }
  function privacy(change: Partial<typeof widget.privacy>) {
    autosave.patch({ privacy: { ...widget.privacy, ...change } });
  }

  function number(event: Event, apply: (value: number) => void) {
    const value = Number((event.currentTarget as HTMLInputElement).value);
    if (Number.isFinite(value)) apply(value);
  }

  const fromLines = (value: string) =>
    value
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);

  // Local text for the origins so a trailing newline is not eaten while
  // typing; the widget gets the parsed list.
  let originsText = $state(untrack(() => (autosave.widget.allowed_origins ?? []).join("\n")));

  const languages = $derived([
    { value: "auto", label: m.widget_admin_language_auto() },
    { value: "sv", label: m.widget_admin_language_sv() },
    { value: "en", label: m.widget_admin_language_en() }
  ]);
</script>

<Settings.Page>
  <Settings.Group title={m.general()}>
    <Settings.Row title={m.name()} description={m.widget_admin_name_description()} let:aria>
      <input
        type="text"
        class={inputClass}
        maxlength="100"
        {...aria}
        value={widget.name}
        oninput={(event) => autosave.patch({ name: event.currentTarget.value })}
      />
    </Settings.Row>
    <Settings.Row
      title={m.widget_admin_language()}
      description={m.widget_admin_language_description()}
      let:aria
    >
      <select
        class={inputClass}
        {...aria}
        value={widget.language}
        onchange={(event) =>
          autosave.patch({ language: event.currentTarget.value as typeof widget.language })}
      >
        {#each languages as option (option.value)}
          <option value={option.value}>{option.label}</option>
        {/each}
      </select>
    </Settings.Row>
    {#if templates.length > 0 && widget.status !== "archived"}
      <Settings.Row
        title={m.widget_admin_template()}
        description={m.widget_admin_template_apply_description()}
        let:aria
      >
        <div class="flex flex-col gap-2 sm:flex-row">
          <select class={inputClass} {...aria} bind:value={selectedTemplate}>
            <option value="">{m.widget_admin_template_choose()}</option>
            {#each templates as template (template.id)}
              <option value={template.id}>
                {template.name}{template.is_default
                  ? ` (${m.widget_admin_template_default()})`
                  : ""}
              </option>
            {/each}
          </select>
          <Button
            variant="outlined"
            onclick={applyTemplate}
            disabled={!selectedTemplate || applying}
            aria-disabled={!selectedTemplate}>{m.widget_admin_template_apply()}</Button
          >
        </div>
      </Settings.Row>
    {/if}
    {#if !assistantPublished}
      <Settings.Row
        title={m.widget_admin_assistant_unpublished_title()}
        description={m.widget_admin_assistant_unpublished_description()}
      >
        <span class="sr-only">{m.widget_admin_assistant_unpublished_title()}</span>
      </Settings.Row>
    {/if}
  </Settings.Group>

  <Settings.Group title={m.widget_admin_texts()}>
    <WidgetTextsFields texts={widget.texts} onChange={texts} />
  </Settings.Group>

  <Settings.Group title={m.widget_admin_appearance()}>
    <WidgetThemeFields theme={widget.theme} onChange={theme} />
  </Settings.Group>

  <Settings.Group title={m.widget_admin_placement()}>
    <Settings.Row
      title={m.widget_admin_allowed_origins()}
      description={m.widget_admin_allowed_origins_description()}
      let:aria
    >
      <textarea
        class={textareaClass}
        placeholder={m.widget_admin_allowed_origins_placeholder()}
        aria-invalid={widget.allowed_origins.length === 0}
        {...aria}
        bind:value={originsText}
        onchange={() => autosave.patch({ allowed_origins: fromLines(originsText) })}></textarea>
      <p class="text-secondary mt-2 text-sm">{m.widget_admin_allowed_origins_help()}</p>
    </Settings.Row>
  </Settings.Group>

  <Settings.Group title={m.widget_admin_limits()}>
    <Settings.Row
      title={m.widget_admin_messages_per_ip()}
      description={m.widget_admin_messages_per_ip_description()}
      let:aria
    >
      <input
        type="number"
        class={inputClass}
        min="1"
        max="1000"
        {...aria}
        value={widget.limits.messages_per_ip_hour}
        oninput={(event) => number(event, (value) => limits({ messages_per_ip_hour: value }))}
      />
    </Settings.Row>
    <Settings.Row
      title={m.widget_admin_daily_budget()}
      description={policy
        ? m.widget_admin_daily_budget_description_policy({
            max: policy.max_daily_token_budget.toLocaleString()
          })
        : m.widget_admin_daily_budget_description()}
      let:aria
    >
      <input
        type="number"
        class={inputClass}
        min="1000"
        step="1000"
        max={policy?.max_daily_token_budget}
        {...aria}
        value={widget.limits.daily_token_budget}
        oninput={(event) => number(event, (value) => limits({ daily_token_budget: value }))}
      />
    </Settings.Row>
    <Settings.Row
      title={m.widget_admin_max_question_chars()}
      description={m.widget_admin_max_question_chars_description()}
      let:aria
    >
      <input
        type="number"
        class={inputClass}
        min="100"
        max="8000"
        step="100"
        {...aria}
        value={widget.limits.max_question_chars}
        oninput={(event) => number(event, (value) => limits({ max_question_chars: value }))}
      />
    </Settings.Row>
    <Settings.Row
      title={m.widget_admin_max_turns()}
      description={m.widget_admin_max_turns_description()}
      let:aria
    >
      <input
        type="number"
        class={inputClass}
        min="1"
        max="100"
        {...aria}
        value={widget.limits.max_session_turns}
        oninput={(event) => number(event, (value) => limits({ max_session_turns: value }))}
      />
    </Settings.Row>
  </Settings.Group>

  <Settings.Group title={m.widget_admin_privacy()}>
    <Settings.Row
      title={m.widget_admin_retention()}
      description={policy
        ? m.widget_admin_retention_description_policy({
            min: String(policy.min_retention_days),
            max: String(policy.max_retention_days)
          })
        : m.widget_admin_retention_description()}
      let:aria
    >
      <input
        type="number"
        class={inputClass}
        min={policy?.min_retention_days ?? 0}
        max={policy?.max_retention_days ?? 3650}
        {...aria}
        value={widget.privacy.retention_days}
        oninput={(event) => number(event, (value) => privacy({ retention_days: value }))}
      />
    </Settings.Row>
    <Settings.Row
      title={m.widget_admin_store_feedback_text()}
      description={m.widget_admin_store_feedback_text_description()}
    >
      <div class="border-default flex h-14 items-center border-b">
        <Input.Switch
          value={widget.privacy.store_feedback_text}
          sideEffect={({ next }) => privacy({ store_feedback_text: next })}
        >
          {m.widget_admin_store_feedback_text()}
        </Input.Switch>
      </div>
    </Settings.Row>
  </Settings.Group>

  <Settings.Group title={m.widget_admin_protection()}>
    <Settings.Row
      title={m.widget_admin_bot_protection()}
      description={m.widget_admin_bot_protection_description()}
      let:aria
    >
      <select
        class={inputClass}
        {...aria}
        value={widget.bot_protection}
        onchange={(event) =>
          autosave.patch({
            bot_protection: event.currentTarget.value as typeof widget.bot_protection
          })}
      >
        <option value="altcha">{m.widget_admin_bot_protection_altcha()}</option>
        <option value="none" disabled={policy ? !policy.allow_bot_protection_none : false}
          >{m.widget_admin_bot_protection_none()}</option
        >
      </select>
    </Settings.Row>
  </Settings.Group>
</Settings.Page>
