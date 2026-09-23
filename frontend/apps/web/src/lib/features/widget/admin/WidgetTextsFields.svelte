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
  import type { LockedTextField } from "./templateLocks";
  import { TextDraft } from "./textDraft.svelte";

  type Props = {
    texts: WidgetTexts;
    onChange: (change: Partial<WidgetTexts>) => void;
    /** Suggested questions belong to a widget, not to a template. */
    showSuggestions?: boolean;
    idPrefix?: string;
    /** Fields a template governs: shown read-only with `lockHint` as their reason. */
    lockedFields?: ReadonlySet<LockedTextField>;
    lockHint?: string;
    /** Why the server refused a text, by field name. */
    errors?: Partial<Record<keyof WidgetTexts, string>>;
    /**
     * Why the subtitle may not be emptied here (a live widget, a template
     * that locks it). A blank subtitle then stays in the field with this
     * message instead of being sent to a server that refuses it.
     */
    subtitleRequired?: string;
    /** Told whether the suggested questions hold edits that cannot be sent yet. */
    onQuestionsHeld?: (held: boolean) => void;
    /** Id of an error about the whole texts group, which every field points to. */
    groupErrorId?: string;
  };

  let {
    texts,
    onChange,
    showSuggestions = true,
    idPrefix = "widget",
    lockedFields = new Set<LockedTextField>(),
    lockHint = "",
    errors = {},
    subtitleRequired,
    onQuestionsHeld,
    groupErrorId
  }: Props = $props();

  const id = (name: string) => `${idPrefix}-${name}`;
  const locked = (field: LockedTextField) => lockedFields.has(field);
  const describedBy = (field: LockedTextField, help: string) =>
    [
      id(help),
      locked(field) && id("lock-hint"),
      problems[field] && id(`${field}-error`),
      groupErrorId
    ]
      .filter(Boolean)
      .join(" ");

  // Typed texts stay as typed while the saved copy is only their normalised form.
  const DRAFTED = [
    "title",
    "welcome",
    "placeholder",
    "subtitle",
    "footer_text",
    "footer_link_label"
  ] as const;
  type Drafted = (typeof DRAFTED)[number];
  const drafts = Object.fromEntries(
    DRAFTED.map((field) => [field, new TextDraft(() => texts[field] ?? "")])
  ) as Record<Drafted, TextDraft>;
  const typed = (field: Drafted) => (event: Event & { currentTarget: { value: string } }) => {
    drafts[field].text = event.currentTarget.value;
    if (field === "subtitle" && subtitleRequired && !event.currentTarget.value.trim()) return;
    const change: Partial<WidgetTexts> = { [field]: event.currentTarget.value };
    onChange(change);
  };
  const problems = $derived<Partial<Record<keyof WidgetTexts, string>>>({
    ...errors,
    subtitle:
      errors.subtitle ??
      (subtitleRequired && !drafts.subtitle.text.trim() ? subtitleRequired : undefined)
  });
  const subtitleInvalid = $derived(!drafts.subtitle.text.trim() || !!problems.subtitle);

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

{#snippet fieldError(field: keyof WidgetTexts)}
  {#if problems[field]}
    <Field.Error id={id(`${field}-error`)}>{problems[field]}</Field.Error>
  {/if}
{/snippet}

<Field.Group class="grid gap-6">
  {#if lockedFields.size > 0}
    <p id={id("lock-hint")} class="text-secondary text-sm">{lockHint}</p>
  {/if}
  <Field.Field>
    <Field.Label for={id("title")}>{m.widget_admin_text_title()}</Field.Label>
    <Input
      id={id("title")}
      maxlength={80}
      value={drafts.title.text}
      disabled={locked("title")}
      aria-invalid={!!errors.title}
      aria-describedby={describedBy("title", "title-help")}
      onfocus={drafts.title.focus}
      onblur={drafts.title.blur}
      oninput={typed("title")}
    />
    <Field.Description id={id("title-help")}
      >{m.widget_admin_text_title_description()}</Field.Description
    >
    {@render fieldError("title")}
  </Field.Field>

  <Field.Field>
    <Field.Label for={id("welcome")}>{m.widget_admin_text_welcome()}</Field.Label>
    <Textarea
      id={id("welcome")}
      maxlength={500}
      rows={3}
      value={drafts.welcome.text}
      disabled={locked("welcome")}
      aria-invalid={!!errors.welcome}
      aria-describedby={describedBy("welcome", "welcome-help")}
      onfocus={drafts.welcome.focus}
      onblur={drafts.welcome.blur}
      oninput={typed("welcome")}
    />
    <Field.Description id={id("welcome-help")}
      >{m.widget_admin_text_welcome_description()}</Field.Description
    >
    {@render fieldError("welcome")}
  </Field.Field>

  {#if showSuggestions}
    <Field.Field>
      <Field.Title>{m.widget_admin_text_suggestions()}</Field.Title>
      <Field.Description>{m.widget_admin_text_suggestions_description()}</Field.Description>
      <SuggestedQuestionsEditor
        id={id("questions")}
        questions={texts.suggested_questions ?? []}
        error={errors.suggested_questions}
        onHeld={onQuestionsHeld}
        describedBy={groupErrorId}
        onChange={(questions) => onChange({ suggested_questions: questions })}
      />
    </Field.Field>
  {/if}

  <Field.Field>
    <Field.Label for={id("placeholder")}>{m.widget_admin_text_placeholder()}</Field.Label>
    <Input
      id={id("placeholder")}
      maxlength={120}
      value={drafts.placeholder.text}
      disabled={locked("placeholder")}
      aria-invalid={!!errors.placeholder}
      aria-describedby={describedBy("placeholder", "placeholder-help")}
      onfocus={drafts.placeholder.focus}
      onblur={drafts.placeholder.blur}
      oninput={typed("placeholder")}
    />
    <Field.Description id={id("placeholder-help")}
      >{m.widget_admin_text_placeholder_description()}</Field.Description
    >
    {@render fieldError("placeholder")}
  </Field.Field>

  <Field.Separator />

  <Field.Field data-invalid={subtitleInvalid || undefined}>
    <Field.Label for={id("subtitle")}>{m.widget_admin_text_subtitle()}</Field.Label>
    <Textarea
      id={id("subtitle")}
      maxlength={300}
      rows={2}
      required
      aria-required="true"
      aria-invalid={subtitleInvalid}
      value={drafts.subtitle.text}
      disabled={locked("subtitle")}
      aria-describedby={describedBy("subtitle", "subtitle-help")}
      onfocus={drafts.subtitle.focus}
      onblur={drafts.subtitle.blur}
      oninput={typed("subtitle")}
    />
    <Field.Description id={id("subtitle-help")}
      >{m.widget_admin_text_subtitle_description()}</Field.Description
    >
    {@render fieldError("subtitle")}
  </Field.Field>

  <Field.Field>
    <Field.Label for={id("footer")}>{m.widget_admin_text_footer()}</Field.Label>
    <Textarea
      id={id("footer")}
      maxlength={300}
      rows={2}
      value={drafts.footer_text.text}
      disabled={locked("footer_text")}
      aria-invalid={!!errors.footer_text}
      aria-describedby={describedBy("footer_text", "footer-help")}
      onfocus={drafts.footer_text.focus}
      onblur={drafts.footer_text.blur}
      oninput={typed("footer_text")}
    />
    <Field.Description id={id("footer-help")}
      >{m.widget_admin_text_footer_description()}</Field.Description
    >
    {@render fieldError("footer_text")}
  </Field.Field>

  <Field.Group class="grid gap-6 sm:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
    <Field.Field data-invalid={linkInvalid || !!errors.footer_link_url || undefined}>
      <Field.Label for={id("footer-link")}>{m.widget_admin_text_footer_link_url()}</Field.Label>
      <Input
        id={id("footer-link")}
        type="url"
        maxlength={500}
        aria-invalid={linkInvalid || !!errors.footer_link_url}
        disabled={locked("footer_link_url")}
        aria-describedby={linkInvalid
          ? `${describedBy("footer_link_url", "footer-link-help")} ${id("footer-link-error")}`
          : describedBy("footer_link_url", "footer-link-help")}
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
        <Field.Error id={id("footer-link-error")}>{m.widget_admin_url_invalid()}</Field.Error>
      {:else}
        {@render fieldError("footer_link_url")}
      {/if}
    </Field.Field>

    <Field.Field>
      <Field.Label for={id("footer-link-label")}
        >{m.widget_admin_text_footer_link_label()}</Field.Label
      >
      <Input
        id={id("footer-link-label")}
        maxlength={80}
        value={drafts.footer_link_label.text}
        disabled={locked("footer_link_label")}
        aria-invalid={!!errors.footer_link_label}
        aria-describedby={describedBy("footer_link_label", "footer-link-label-help")}
        onfocus={drafts.footer_link_label.focus}
        onblur={drafts.footer_link_label.blur}
        oninput={typed("footer_link_label")}
      />
      <Field.Description id={id("footer-link-label-help")}
        >{m.widget_admin_text_footer_link_label_description()}</Field.Description
      >
      {@render fieldError("footer_link_label")}
    </Field.Field>
  </Field.Group>
</Field.Group>
