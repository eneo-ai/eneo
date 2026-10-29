"use client";

import { TextArea } from "@astryxdesign/core/TextArea";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { TextInput } from "@/components/astryx/text-input";
import type { Schema } from "@/lib/api/models";
import { isHttpUrl } from "../urls";
import { SuggestedQuestionsEditor } from "./suggested-questions-editor";
import type { LockedTextField } from "./template-locks";
import { DraftWrapper, useTextDraft } from "./use-text-draft";

type WidgetTexts = Schema<"WidgetTexts">;

type Drafted =
  "title" | "welcome" | "placeholder" | "subtitle" | "footer_text" | "footer_link_label";

/** A text the editor types, shown as typed while the saved copy is its normalised form. */
function DraftedText({
  field,
  texts,
  multiline = false,
  rows,
  maxLength,
  label,
  description,
  locked,
  lockHint,
  error,
  required,
  onTyped
}: {
  field: Drafted;
  texts: WidgetTexts;
  multiline?: boolean;
  rows?: number;
  maxLength: number;
  label: string;
  description: string;
  locked: boolean;
  lockHint: string;
  error?: string;
  required?: boolean;
  onTyped: (value: string) => void;
}) {
  const draft = useTextDraft(texts[field] ?? "");
  const status = error ? ({ type: "error", message: error } as const) : undefined;
  const change = (value: string) => {
    const next = value.slice(0, maxLength);
    draft.setText(next);
    onTyped(next);
  };
  if (multiline) {
    return (
      <TextArea
        label={label}
        description={description}
        rows={rows}
        maxLength={maxLength}
        value={draft.text}
        onChange={change}
        onFocus={draft.onFocus}
        onBlur={draft.onBlur}
        isDisabled={locked}
        disabledMessage={locked ? lockHint : undefined}
        isRequired={required}
        status={status}
        width="100%"
      />
    );
  }
  return (
    <DraftWrapper onFocus={draft.onFocus} onBlur={draft.onBlur}>
      <TextInput
        label={label}
        description={description}
        value={draft.text}
        onChange={change}
        isDisabled={locked}
        disabledMessage={locked ? lockHint : undefined}
        isRequired={required}
        status={status}
        width="100%"
      />
    </DraftWrapper>
  );
}

/** A link address, committed when the field is left, never per keystroke. */
function LinkField({
  value,
  label,
  description,
  locked,
  lockHint,
  error,
  onCommit
}: {
  value: string;
  label: string;
  description: string;
  locked: boolean;
  lockHint: string;
  error?: string;
  onCommit: (value: string | null) => void;
}) {
  const t = useTranslations();
  const [draft, setDraft] = useState(value);
  const [invalid, setInvalid] = useState(false);
  // Follow a new saved value (template applied, other tab) without ever
  // touching what is being typed. Adjusted during render.
  const [seen, setSeen] = useState(value);
  if (value !== seen) {
    setSeen(value);
    setDraft(value);
    setInvalid(false);
  }
  function commit() {
    const trimmed = draft.trim();
    if (trimmed === "") {
      setInvalid(false);
      if (value) onCommit(null);
      return;
    }
    const bad = !isHttpUrl(trimmed);
    setInvalid(bad);
    if (!bad && trimmed !== value) onCommit(trimmed);
  }
  const message = invalid ? t("widget_admin_url_invalid") : error;
  return (
    <DraftWrapper onFocus={() => {}} onBlur={commit}>
      <TextInput
        label={label}
        description={description}
        value={draft}
        onChange={(next) => setDraft(next.slice(0, 500))}
        onEnter={commit}
        isDisabled={locked}
        disabledMessage={locked ? lockHint : undefined}
        status={message ? { type: "error", message } : undefined}
        width="100%"
      />
    </DraftWrapper>
  );
}

/** The visitor-facing texts, in the order they appear in the chat panel. */
export function WidgetTextsFields({
  texts,
  onChange,
  showSuggestions = true,
  lockedFields = new Set<LockedTextField>(),
  lockHint = "",
  errors = {},
  subtitleRequired,
  onQuestionsHeld
}: {
  texts: WidgetTexts;
  onChange: (change: Partial<WidgetTexts>) => void;
  /** Suggested questions belong to a widget, not to a template. */
  showSuggestions?: boolean;
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
}) {
  const t = useTranslations();
  const locked = (field: LockedTextField) => lockedFields.has(field);

  // A blank subtitle held back while it may not be emptied; sent as soon as
  // it may be (the widget is paused, the template unlocks it).
  const [heldSubtitle, setHeldSubtitle] = useState<string | null>(null);
  const [wasRequired, setWasRequired] = useState(!!subtitleRequired);
  if (!!subtitleRequired !== wasRequired) {
    setWasRequired(!!subtitleRequired);
    if (!subtitleRequired && heldSubtitle !== null) {
      setHeldSubtitle(null);
      onChange({ subtitle: heldSubtitle });
    }
  }

  const subtitleProblem =
    errors.subtitle ?? (heldSubtitle !== null && subtitleRequired ? subtitleRequired : undefined);

  const typed = (field: Drafted) => (value: string) => {
    if (field === "subtitle") {
      if (subtitleRequired && !value.trim()) {
        setHeldSubtitle(value);
        return;
      }
      setHeldSubtitle(null);
    }
    onChange({ [field]: value });
  };

  return (
    <div className="flex flex-col gap-6">
      {lockedFields.size > 0 && <p className="text-ax-text-secondary text-sm">{lockHint}</p>}
      <DraftedText
        field="title"
        texts={texts}
        maxLength={80}
        label={t("widget_admin_text_title")}
        description={t("widget_admin_text_title_description")}
        locked={locked("title")}
        lockHint={lockHint}
        error={errors.title}
        onTyped={typed("title")}
      />
      <DraftedText
        field="welcome"
        texts={texts}
        multiline
        rows={3}
        maxLength={500}
        label={t("widget_admin_text_welcome")}
        description={t("widget_admin_text_welcome_description")}
        locked={locked("welcome")}
        lockHint={lockHint}
        error={errors.welcome}
        onTyped={typed("welcome")}
      />
      {showSuggestions && (
        <div className="flex flex-col gap-2">
          <p className="text-sm font-medium">{t("widget_admin_text_suggestions")}</p>
          <p className="text-ax-text-secondary text-sm">
            {t("widget_admin_text_suggestions_description")}
          </p>
          <SuggestedQuestionsEditor
            questions={texts.suggested_questions ?? []}
            error={errors.suggested_questions}
            onHeld={onQuestionsHeld}
            onChange={(questions) => onChange({ suggested_questions: questions })}
          />
        </div>
      )}
      <DraftedText
        field="placeholder"
        texts={texts}
        maxLength={120}
        label={t("widget_admin_text_placeholder")}
        description={t("widget_admin_text_placeholder_description")}
        locked={locked("placeholder")}
        lockHint={lockHint}
        error={errors.placeholder}
        onTyped={typed("placeholder")}
      />
      <hr className="border-ax-border" />
      <DraftedText
        field="subtitle"
        texts={texts}
        multiline
        rows={2}
        maxLength={300}
        label={t("widget_admin_text_subtitle")}
        description={t("widget_admin_text_subtitle_description")}
        locked={locked("subtitle")}
        lockHint={lockHint}
        error={subtitleProblem}
        required
        onTyped={typed("subtitle")}
      />
      <DraftedText
        field="footer_text"
        texts={texts}
        multiline
        rows={2}
        maxLength={300}
        label={t("widget_admin_text_footer")}
        description={t("widget_admin_text_footer_description")}
        locked={locked("footer_text")}
        lockHint={lockHint}
        error={errors.footer_text}
        onTyped={typed("footer_text")}
      />
      <div className="grid gap-6 sm:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <LinkField
          value={texts.footer_link_url ?? ""}
          label={t("widget_admin_text_footer_link_url")}
          description={t("widget_admin_text_footer_link_url_description")}
          locked={locked("footer_link_url")}
          lockHint={lockHint}
          error={errors.footer_link_url}
          onCommit={(footer_link_url) => onChange({ footer_link_url })}
        />
        <DraftedText
          field="footer_link_label"
          texts={texts}
          maxLength={80}
          label={t("widget_admin_text_footer_link_label")}
          description={t("widget_admin_text_footer_link_label_description")}
          locked={locked("footer_link_label")}
          lockHint={lockHint}
          error={errors.footer_link_label}
          onTyped={typed("footer_link_label")}
        />
      </div>
    </div>
  );
}
