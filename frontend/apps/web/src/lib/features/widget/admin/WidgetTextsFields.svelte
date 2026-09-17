<!-- The visitor-facing texts, shared by the widget page and the template editor. -->
<script lang="ts">
  import type { WidgetTexts } from "@eneo/eneo-js";
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import { untrack } from "svelte";
  import { inputClass, textareaClass } from "./fieldStyles";

  type Props = {
    texts: WidgetTexts;
    onChange: (change: Partial<WidgetTexts>) => void;
  };

  let { texts, onChange }: Props = $props();

  const fromLines = (value: string) =>
    value
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);

  // Local text so a trailing newline is not eaten while typing.
  let suggestionsText = $state(untrack(() => (texts.suggested_questions ?? []).join("\n")));
</script>

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
    value={texts.title ?? ""}
    oninput={(event) => onChange({ title: event.currentTarget.value })}
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
    value={texts.welcome ?? ""}
    oninput={(event) => onChange({ welcome: event.currentTarget.value })}></textarea>
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
    value={texts.placeholder ?? ""}
    oninput={(event) => onChange({ placeholder: event.currentTarget.value })}
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
    oninput={() => onChange({ suggested_questions: fromLines(suggestionsText).slice(0, 5) })}
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
    aria-invalid={!(texts.ai_disclosure ?? "").trim()}
    {...aria}
    value={texts.ai_disclosure ?? ""}
    oninput={(event) => onChange({ ai_disclosure: event.currentTarget.value })}></textarea>
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
    value={texts.personal_data_notice ?? ""}
    oninput={(event) => onChange({ personal_data_notice: event.currentTarget.value })}></textarea>
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
    value={texts.privacy_url ?? ""}
    oninput={(event) => onChange({ privacy_url: event.currentTarget.value.trim() || null })}
  />
</Settings.Row>
