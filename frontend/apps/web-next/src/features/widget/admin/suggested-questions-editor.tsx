"use client";

import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState } from "react";
import { TextInput } from "@/components/astryx/text-input";
import { collapseWhitespace } from "./text";
import { DraftWrapper } from "./use-text-draft";

// Mirrors MAX_SUGGESTED_QUESTIONS in the backend's WidgetTexts.
const MAX = 4;
const MAX_LENGTH = 120;

type Row = { key: number; text: string };

/** What the API stores for a list of rows: whitespace collapsed, blanks dropped. */
const clean = (texts: string[]) => texts.map(collapseWhitespace).filter(Boolean);

/**
 * The suggested questions a visitor can tap before typing: one input per
 * question, add with a button, remove per row. Announces changes for screen
 * readers and keeps focus sensible when rows come and go.
 */
export function SuggestedQuestionsEditor({
  questions,
  onChange,
  error = "",
  onHeld
}: {
  questions: string[];
  onChange: (questions: string[]) => void;
  /** Why the server refused the saved list. */
  error?: string;
  /** Told whether the rows hold edits that cannot be sent yet (a repeated question). */
  onHeld?: (held: boolean) => void;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const id = useId();
  const inputs = useRef(new Map<number, HTMLInputElement | null>());
  const addButton = useRef<HTMLDivElement>(null);
  // Rows keep their identity while editing so a cleared row does not vanish.
  // Keys are handed out from state, as render may need fresh ones.
  const [rows, setRows] = useState<Row[]>(() => questions.map((text, key) => ({ key, text })));
  const [nextKey, setNextKey] = useState(questions.length);
  // Adopt a list only when it is news: a template applied, a reload. Every
  // save answers with a fresh copy of the list just sent, which must never
  // replace rows, least of all a new row that is still being typed.
  const incoming = clean(questions).join("\n");
  const [seen, setSeen] = useState(incoming);
  // What was last sent or adopted; a save's echo of it is not an edit.
  const [sent, setSent] = useState(incoming);
  if (incoming !== seen) {
    setSeen(incoming);
    setSent(incoming);
    if (clean(rows.map((row) => row.text)).join("\n") !== incoming) {
      setRows(questions.map((text, offset) => ({ key: nextKey + offset, text })));
      setNextKey(nextKey + questions.length);
    }
  }

  // The API refuses a repeated question, and the visitor's chips are keyed by it.
  const texts = rows.map((row) => collapseWhitespace(row.text));
  const duplicates = rows
    .filter((_, index) => texts[index] && texts.indexOf(texts[index]!) < index)
    .map((row) => row.key);
  const held = duplicates.length > 0;
  useEffect(() => {
    onHeld?.(held);
    return () => onHeld?.(false);
  }, [held, onHeld]);

  function emit(current: Row[]) {
    if (duplicates.length > 0) return;
    const next = clean(current.map((row) => row.text));
    // Leaving a row unchanged is not an edit: sending the list again would
    // also resend whatever else the texts group holds back.
    if (next.join("\n") === sent) return;
    setSent(next.join("\n"));
    onChange(next);
  }

  function add() {
    if (rows.length >= MAX) return;
    const key = nextKey;
    setNextKey(key + 1);
    const next = [...rows, { key, text: "" }];
    setRows(next);
    announce(t("widget_admin_questions_added", { count: next.length }));
    requestAnimationFrame(() => inputs.current.get(key)?.focus());
  }

  function remove(index: number) {
    const next = rows.filter((_, i) => i !== index);
    setRows(next);
    emit(next);
    announce(t("widget_admin_questions_removed", { count: next.length }));
    requestAnimationFrame(() => {
      const following = next[Math.min(index, next.length - 1)];
      if (following) inputs.current.get(following.key)?.focus();
      else addButton.current?.querySelector("button")?.focus();
    });
  }

  return (
    <div className="flex flex-col gap-3">
      {rows.length === 0 && (
        <p className="text-ax-text-secondary text-sm">{t("widget_admin_questions_empty_hint")}</p>
      )}
      <ol className="flex flex-col gap-2" aria-label={t("widget_admin_text_suggestions")}>
        {rows.map((row, index) => {
          const duplicate = duplicates.includes(row.key);
          return (
            <li key={row.key} className="flex items-start gap-2">
              <DraftWrapper className="flex-1" onFocus={() => {}} onBlur={() => emit(rows)}>
                <TextInput
                  ref={(input) => {
                    inputs.current.set(row.key, input);
                  }}
                  label={t("widget_admin_questions_label", { index: index + 1 })}
                  isLabelHidden
                  value={row.text}
                  placeholder={t("widget_admin_questions_placeholder")}
                  onChange={(text) =>
                    setRows((current) =>
                      current.map((r) =>
                        r.key === row.key ? { ...r, text: text.slice(0, MAX_LENGTH) } : r
                      )
                    )
                  }
                  onEnter={() => {
                    emit(rows);
                    if (index === rows.length - 1) add();
                  }}
                  status={
                    duplicate
                      ? { type: "error", message: t("widget_admin_questions_duplicate") }
                      : undefined
                  }
                  aria-describedby={error ? `${id}-error` : undefined}
                  width="100%"
                />
              </DraftWrapper>
              <IconButton
                variant="ghost"
                label={t("widget_admin_questions_remove", { index: index + 1 })}
                icon={<X aria-hidden="true" className="size-4" />}
                onClick={() => remove(index)}
              />
            </li>
          );
        })}
      </ol>
      {error && (
        <p className="text-ax-red text-sm" id={`${id}-error`}>
          {error}
        </p>
      )}
      <div className="flex items-center justify-between gap-3">
        <div ref={addButton} className="contents">
          <Button
            size="sm"
            label={t("widget_admin_questions_add")}
            icon={<Plus aria-hidden="true" className="size-4" />}
            isDisabled={rows.length >= MAX}
            onClick={add}
          />
        </div>
        <span className="text-ax-text-secondary text-xs">
          {t("widget_admin_questions_limit", { count: rows.length, max: MAX })}
        </span>
      </div>
    </div>
  );
}
