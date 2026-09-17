<!--
  Everything an editor configures on a widget. Each field patches the
  autosave immediately; nested groups are sent whole because the API replaces
  them as units.
-->
<script lang="ts">
  import type { WidgetPolicy } from "@eneo/eneo-js";
  import { Input } from "@eneo/ui";
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import { untrack } from "svelte";
  import { contrastVerdict, DEFAULT_PRIMARY_COLOR, isHexColor } from "./contrast";
  import type { WidgetAutosave } from "./widgetAutosave.svelte";

  type Props = {
    autosave: WidgetAutosave;
    policy: WidgetPolicy | null;
    assistantPublished: boolean;
  };

  let { autosave, policy, assistantPublished }: Props = $props();

  const widget = $derived(autosave.widget);

  const inputClass =
    "border-default bg-primary ring-default rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2 w-full";
  const textareaClass = `${inputClass} min-h-24 placeholder:text-muted`;

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

  const lines = (values: string[] | undefined) => (values ?? []).join("\n");
  const fromLines = (value: string) =>
    value
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);

  // Local text for the origins and suggestions so a trailing newline is not
  // eaten while typing; the widget gets the parsed list.
  let originsText = $state(untrack(() => lines(autosave.widget.allowed_origins)));
  let suggestionsText = $state(untrack(() => lines(autosave.widget.texts.suggested_questions)));

  const primaryColor = $derived(widget.theme.primary_color ?? DEFAULT_PRIMARY_COLOR);
  const contrast = $derived(contrastVerdict(primaryColor));
  const contrastLabel = $derived.by(() => {
    const ratio = contrast.ratio.toFixed(1);
    switch (contrast.verdict) {
      case "text":
        return m.widget_admin_contrast_ok({ ratio });
      case "graphics":
        return m.widget_admin_contrast_graphics_only({ ratio });
      case "fail":
        return m.widget_admin_contrast_fail({ ratio });
      default:
        return m.widget_admin_contrast_invalid();
    }
  });

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
    <Settings.Row
      title={m.widget_admin_text_title()}
      description={m.widget_admin_text_title_description()}
      let:aria
    >
      <input
        type="text"
        class={inputClass}
        maxlength="80"
        {...aria}
        value={widget.texts.title}
        oninput={(event) => texts({ title: event.currentTarget.value })}
      />
    </Settings.Row>
    <Settings.Row
      title={m.widget_admin_text_welcome()}
      description={m.widget_admin_text_welcome_description()}
      let:aria
    >
      <textarea
        class={textareaClass}
        maxlength="500"
        {...aria}
        value={widget.texts.welcome}
        oninput={(event) => texts({ welcome: event.currentTarget.value })}></textarea>
    </Settings.Row>
    <Settings.Row
      title={m.widget_admin_text_placeholder()}
      description={m.widget_admin_text_placeholder_description()}
      let:aria
    >
      <input
        type="text"
        class={inputClass}
        maxlength="120"
        {...aria}
        value={widget.texts.placeholder}
        oninput={(event) => texts({ placeholder: event.currentTarget.value })}
      />
    </Settings.Row>
    <Settings.Row
      title={m.widget_admin_text_suggestions()}
      description={m.widget_admin_text_suggestions_description()}
      let:aria
    >
      <textarea
        class={textareaClass}
        {...aria}
        bind:value={suggestionsText}
        oninput={() => texts({ suggested_questions: fromLines(suggestionsText).slice(0, 5) })}
      ></textarea>
    </Settings.Row>
    <Settings.Row
      title={m.widget_admin_text_disclosure()}
      description={m.widget_admin_text_disclosure_description()}
      let:aria
    >
      <textarea
        class={textareaClass}
        maxlength="300"
        required
        aria-required="true"
        aria-invalid={!(widget.texts.ai_disclosure ?? "").trim()}
        {...aria}
        value={widget.texts.ai_disclosure}
        oninput={(event) => texts({ ai_disclosure: event.currentTarget.value })}></textarea>
    </Settings.Row>
    <Settings.Row
      title={m.widget_admin_text_personal_data()}
      description={m.widget_admin_text_personal_data_description()}
      let:aria
    >
      <textarea
        class={textareaClass}
        maxlength="300"
        {...aria}
        value={widget.texts.personal_data_notice}
        oninput={(event) => texts({ personal_data_notice: event.currentTarget.value })}></textarea>
    </Settings.Row>
    <Settings.Row
      title={m.widget_admin_text_privacy_url()}
      description={m.widget_admin_text_privacy_url_description()}
      let:aria
    >
      <input
        type="url"
        class={inputClass}
        maxlength="500"
        {...aria}
        value={widget.texts.privacy_url ?? ""}
        oninput={(event) => texts({ privacy_url: event.currentTarget.value.trim() || null })}
      />
    </Settings.Row>
  </Settings.Group>

  <Settings.Group title={m.widget_admin_appearance()}>
    <Settings.Row
      title={m.widget_admin_primary_color()}
      description={m.widget_admin_primary_color_description()}
      let:aria
    >
      <div class="flex items-center gap-3">
        <input
          type="color"
          class="border-default h-10 w-14 cursor-pointer rounded-lg border"
          aria-label={m.widget_admin_primary_color_picker()}
          value={isHexColor(primaryColor) ? primaryColor : DEFAULT_PRIMARY_COLOR}
          oninput={(event) => theme({ primary_color: event.currentTarget.value })}
        />
        <input
          type="text"
          class={inputClass}
          pattern="#[0-9a-fA-F]{6}"
          maxlength="7"
          aria-invalid={contrast.verdict === "invalid"}
          {...aria}
          value={primaryColor}
          oninput={(event) => theme({ primary_color: event.currentTarget.value.trim() })}
        />
      </div>
      <p
        class={[
          "mt-2 text-sm",
          contrast.verdict === "text" ? "text-positive-default" : "text-warning-stronger"
        ]}
        aria-live="polite"
      >
        {contrastLabel}
      </p>
    </Settings.Row>
    <Settings.Row
      title={m.widget_admin_color_scheme()}
      description={m.widget_admin_color_scheme_description()}
      let:aria
    >
      <select
        class={inputClass}
        {...aria}
        value={widget.theme.color_scheme}
        onchange={(event) =>
          theme({ color_scheme: event.currentTarget.value as typeof widget.theme.color_scheme })}
      >
        <option value="auto">{m.widget_admin_scheme_auto()}</option>
        <option value="light">{m.widget_admin_scheme_light()}</option>
        <option value="dark">{m.widget_admin_scheme_dark()}</option>
      </select>
    </Settings.Row>
    <Settings.Row
      title={m.widget_admin_position()}
      description={m.widget_admin_position_description()}
      let:aria
    >
      <select
        class={inputClass}
        {...aria}
        value={widget.theme.position}
        onchange={(event) =>
          theme({ position: event.currentTarget.value as typeof widget.theme.position })}
      >
        <option value="bottom-right">{m.widget_admin_position_right()}</option>
        <option value="bottom-left">{m.widget_admin_position_left()}</option>
      </select>
    </Settings.Row>
    <Settings.Row
      title={m.widget_admin_radius()}
      description={m.widget_admin_radius_description()}
      let:aria
    >
      <input
        type="number"
        class={inputClass}
        min="0"
        max="24"
        step="1"
        {...aria}
        value={widget.theme.radius}
        oninput={(event) =>
          number(event, (value) => theme({ radius: Math.min(24, Math.max(0, value)) }))}
      />
    </Settings.Row>
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
