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

  // The footer link is committed when the field is left, never per keystroke.
  let linkDraft = $state(untrack(() => texts.footer_link_url ?? ""));
  let linkInvalid = $state(false);
  let lastSavedLink = untrack(() => texts.footer_link_url ?? "");
  $effect(() => {
    const saved = texts.footer_link_url ?? "";
    if (saved !== lastSavedLink) {
      lastSavedLink = saved;
      linkDraft = saved;
      linkInvalid = false;
    }
  });
  function commitLink() {
    const trimmed = linkDraft.trim();
    if (trimmed === "") {
      linkInvalid = false;
      if (texts.footer_link_url) onChange({ footer_link_url: null });
      return;
    }
    linkInvalid = !isHttpUrl(trimmed);
    if (!linkInvalid && trimmed !== texts.footer_link_url) onChange({ footer_link_url: trimmed });
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

  <Field.Field data-invalid={!(texts.subtitle ?? "").trim() || undefined}>
    <Field.Label for={id("subtitle")}>{m.widget_admin_text_subtitle()}</Field.Label>
    <Textarea
      id={id("subtitle")}
      maxlength={300}
      rows={2}
      required
      aria-required="true"
      aria-invalid={!(texts.subtitle ?? "").trim()}
      value={texts.subtitle ?? ""}
      aria-describedby={id("subtitle-help")}
      oninput={(event) => onChange({ subtitle: event.currentTarget.value })}
    />
    <Field.Description id={id("subtitle-help")}
      >{m.widget_admin_text_subtitle_description()}</Field.Description
    >
  </Field.Field>

  <Field.Field>
    <Field.Label for={id("footer")}>{m.widget_admin_text_footer()}</Field.Label>
    <Textarea
      id={id("footer")}
      maxlength={300}
      rows={2}
      value={texts.footer_text ?? ""}
      aria-describedby={id("footer-help")}
      oninput={(event) => onChange({ footer_text: event.currentTarget.value })}
    />
    <Field.Description id={id("footer-help")}
      >{m.widget_admin_text_footer_description()}</Field.Description
    >
  </Field.Field>

  <Field.Group class="grid gap-6 sm:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
    <Field.Field data-invalid={linkInvalid || undefined}>
      <Field.Label for={id("footer-link")}>{m.widget_admin_text_footer_link_url()}</Field.Label>
      <Input
        id={id("footer-link")}
        type="url"
        maxlength={500}
        aria-invalid={linkInvalid}
        aria-describedby={id("footer-link-help")}
        bind:value={linkDraft}
        onchange={commitLink}
        onkeydown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commitLink();
          }
        }}
      />
      <Field.Description id={id("footer-link-help")}
        >{m.widget_admin_text_footer_link_url_description()}</Field.Description
      >
      {#if linkInvalid}
        <Field.Error>{m.widget_admin_url_invalid()}</Field.Error>
      {/if}
    </Field.Field>

    <Field.Field>
      <Field.Label for={id("footer-link-label")}
        >{m.widget_admin_text_footer_link_label()}</Field.Label
      >
      <Input
        id={id("footer-link-label")}
        maxlength={80}
        value={texts.footer_link_label ?? ""}
        aria-describedby={id("footer-link-label-help")}
        oninput={(event) => onChange({ footer_link_label: event.currentTarget.value })}
      />
      <Field.Description id={id("footer-link-label-help")}
        >{m.widget_admin_text_footer_link_label_description()}</Field.Description
      >
    </Field.Field>
  </Field.Group>
</Field.Group>
