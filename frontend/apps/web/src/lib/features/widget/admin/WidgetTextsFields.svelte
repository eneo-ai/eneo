<!-- The visitor-facing texts, in the order they appear in the chat panel. -->
<script lang="ts">
  import type { WidgetTexts } from "@eneo/eneo-js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { m } from "$lib/paraglide/messages";
  import { untrack } from "svelte";
  import { isHttpUrl } from "../urls";
  import SuggestedQuestionsEditor from "./SuggestedQuestionsEditor.svelte";

  type Props = {
    texts: WidgetTexts;
    onChange: (change: Partial<WidgetTexts>) => void;
    /** Suggested questions belong to a widget, not to a template. */
    showSuggestions?: boolean;
    idPrefix?: string;
  };

  let { texts, onChange, showSuggestions = true, idPrefix = "widget" }: Props = $props();

  const id = (name: string) => `${idPrefix}-${name}`;

  // The privacy link is committed when the field is left, never per keystroke.
  let privacyDraft = $state(untrack(() => texts.privacy_url ?? ""));
  let privacyInvalid = $state(false);
  let lastSavedPrivacy = untrack(() => texts.privacy_url ?? "");
  $effect(() => {
    const saved = texts.privacy_url ?? "";
    if (saved !== lastSavedPrivacy) {
      lastSavedPrivacy = saved;
      privacyDraft = saved;
      privacyInvalid = false;
    }
  });
  function commitPrivacy() {
    const trimmed = privacyDraft.trim();
    if (trimmed === "") {
      privacyInvalid = false;
      if (texts.privacy_url) onChange({ privacy_url: null });
      return;
    }
    privacyInvalid = !isHttpUrl(trimmed);
    if (!privacyInvalid && trimmed !== texts.privacy_url) onChange({ privacy_url: trimmed });
  }
</script>

<Field.Group class="grid gap-6">
  <Field.Field>
    <Field.Label for={id("title")}>{m.widget_admin_text_title()}</Field.Label>
    <Input
      id={id("title")}
      maxlength={80}
      value={texts.title ?? ""}
      aria-describedby={id("title-help")}
      oninput={(event) => onChange({ title: event.currentTarget.value })}
    />
    <Field.Description id={id("title-help")}
      >{m.widget_admin_text_title_description()}</Field.Description
    >
  </Field.Field>

  <Field.Field>
    <Field.Label for={id("welcome")}>{m.widget_admin_text_welcome()}</Field.Label>
    <Textarea
      id={id("welcome")}
      maxlength={500}
      rows={3}
      value={texts.welcome ?? ""}
      aria-describedby={id("welcome-help")}
      oninput={(event) => onChange({ welcome: event.currentTarget.value })}
    />
    <Field.Description id={id("welcome-help")}
      >{m.widget_admin_text_welcome_description()}</Field.Description
    >
  </Field.Field>

  {#if showSuggestions}
    <Field.Field>
      <Field.Title>{m.widget_admin_text_suggestions()}</Field.Title>
      <Field.Description>{m.widget_admin_text_suggestions_description()}</Field.Description>
      <SuggestedQuestionsEditor
        id={id("questions")}
        questions={texts.suggested_questions ?? []}
        onChange={(questions) => onChange({ suggested_questions: questions })}
      />
    </Field.Field>
  {/if}

  <Field.Field>
    <Field.Label for={id("placeholder")}>{m.widget_admin_text_placeholder()}</Field.Label>
    <Input
      id={id("placeholder")}
      maxlength={120}
      value={texts.placeholder ?? ""}
      aria-describedby={id("placeholder-help")}
      oninput={(event) => onChange({ placeholder: event.currentTarget.value })}
    />
    <Field.Description id={id("placeholder-help")}
      >{m.widget_admin_text_placeholder_description()}</Field.Description
    >
  </Field.Field>

  <Field.Separator />

  <Field.Field data-invalid={!(texts.ai_disclosure ?? "").trim() || undefined}>
    <Field.Label for={id("disclosure")}>{m.widget_admin_text_disclosure()}</Field.Label>
    <Textarea
      id={id("disclosure")}
      maxlength={300}
      rows={2}
      required
      aria-required="true"
      aria-invalid={!(texts.ai_disclosure ?? "").trim()}
      value={texts.ai_disclosure ?? ""}
      aria-describedby={id("disclosure-help")}
      oninput={(event) => onChange({ ai_disclosure: event.currentTarget.value })}
    />
    <Field.Description id={id("disclosure-help")}
      >{m.widget_admin_text_disclosure_description()}</Field.Description
    >
  </Field.Field>

  <Field.Field>
    <Field.Label for={id("personal-data")}>{m.widget_admin_text_personal_data()}</Field.Label>
    <Textarea
      id={id("personal-data")}
      maxlength={300}
      rows={2}
      value={texts.personal_data_notice ?? ""}
      aria-describedby={id("personal-data-help")}
      oninput={(event) => onChange({ personal_data_notice: event.currentTarget.value })}
    />
    <Field.Description id={id("personal-data-help")}
      >{m.widget_admin_text_personal_data_description()}</Field.Description
    >
  </Field.Field>

  <Field.Field data-invalid={privacyInvalid || undefined}>
    <Field.Label for={id("privacy-url")}>{m.widget_admin_text_privacy_url()}</Field.Label>
    <Input
      id={id("privacy-url")}
      type="url"
      maxlength={500}
      aria-invalid={privacyInvalid}
      aria-describedby={id("privacy-url-help")}
      bind:value={privacyDraft}
      onchange={commitPrivacy}
      onkeydown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          commitPrivacy();
        }
      }}
    />
    <Field.Description id={id("privacy-url-help")}
      >{m.widget_admin_text_privacy_url_description()}</Field.Description
    >
    {#if privacyInvalid}
      <Field.Error>{m.widget_admin_url_invalid()}</Field.Error>
    {/if}
  </Field.Field>
</Field.Group>
