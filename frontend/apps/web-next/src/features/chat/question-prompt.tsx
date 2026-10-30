"use client";

import { Button } from "@astryxdesign/core/Button";
import { CheckboxList, CheckboxListItem } from "@astryxdesign/core/CheckboxList";
import { useHotkeys } from "@astryxdesign/core/hooks";
import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Token } from "@astryxdesign/core/Token";
import { ArrowUp } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState, type KeyboardEvent } from "react";
import { questionAnswer, type OpenQuestion } from "./questions";

const MAX_HOTKEYS = 4;

/**
 * A question the assistant asked, docked above the composer until it is
 * answered: its options as radios (or checkboxes when several may be
 * picked) and a field for an answer in the person's own words. A single
 * choice sends as soon as it is made, by click or number key, as Claude
 * Code's questions do; several choices wait for the Svara button; the
 * field sends on Enter. Esc in the field moves to the composer, where any
 * message answers the question too. The composer below stays as it is.
 */
export function QuestionPrompt({
  question,
  onAnswer,
  onDismiss,
  sending = false
}: {
  question: OpenQuestion;
  /** Sends the answer as the next message. */
  onAnswer: (text: string) => void;
  /** The person would rather type: focus goes to the composer. */
  onDismiss: () => void;
  sending?: boolean;
}) {
  const t = useTranslations();
  const headingId = useId();
  const [picked, setPicked] = useState<string[]>([]);
  const [other, setOther] = useState("");
  const answer = questionAnswer(question, picked, other);
  const canSend = answer.length > 0 && !sending;
  const labels = question.options.map((option) => option.label);

  const send = () => {
    if (canSend) onAnswer(answer);
  };
  // A single choice is the answer; several are gathered until Svara.
  const pick = (label: string) => {
    if (!question.multiSelect) {
      setPicked([label]);
      if (!sending) onAnswer(questionAnswer(question, [label], ""));
      return;
    }
    setPicked((current) =>
      current.includes(label) ? current.filter((item) => item !== label) : [...current, label]
    );
  };

  // The number keys pick while focus is on the page or in the prompt's
  // options, never while typing (the composer or the free-text field).
  useHotkeys(
    labels.slice(0, MAX_HOTKEYS).map((label, index) => ({
      keys: String(index + 1),
      onPress: () => pick(label)
    }))
  );

  const onFieldKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    onDismiss();
  };

  const hint = t(question.multiSelect ? "chat_question_hint_multi" : "chat_question_hint_single", {
    count: Math.min(labels.length, MAX_HOTKEYS)
  });

  return (
    <section
      aria-labelledby={headingId}
      className="border-ax-border bg-ax-card rounded-ax-chat shadow-ax-med flex w-full flex-col gap-2.5 border p-3.5"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          {question.header && <Token label={question.header} size="sm" color="blue" />}
          <span className="text-ax-text-secondary text-xs">
            {t("chat_question_from_assistant")}
            {question.multiSelect && ` · ${t("chat_question_pick_several")}`}
          </span>
        </div>
        <Button
          variant="ghost"
          size="sm"
          label={t("chat_question_answer_freely")}
          onClick={onDismiss}
        />
      </div>
      <h2 id={headingId} className="m-0 text-[15px] leading-snug font-semibold">
        {question.question}
      </h2>
      {question.multiSelect ? (
        <CheckboxList
          label={question.question}
          isLabelHidden
          value={picked}
          onChange={setPicked}
          density="compact"
        >
          {question.options.map((option) => (
            <CheckboxListItem
              key={option.label}
              value={option.label}
              label={option.label}
              description={option.description ?? undefined}
            />
          ))}
        </CheckboxList>
      ) : (
        <RadioList label={question.question} isLabelHidden value={picked[0] ?? ""} onChange={pick}>
          {question.options.map((option) => (
            <RadioListItem
              key={option.label}
              value={option.label}
              label={option.label}
              description={option.description ?? undefined}
            />
          ))}
        </RadioList>
      )}
      <TextInput
        label={t("chat_question_other")}
        isLabelHidden
        placeholder={t("chat_question_other_placeholder")}
        value={other}
        onChange={(value) => {
          setOther(value);
          // An answer in the person's own words replaces a single pick.
          if (!question.multiSelect && value.trim()) setPicked([]);
        }}
        onEnter={send}
        onKeyDown={onFieldKeyDown}
      />
      <div className="flex min-h-8 items-center justify-between gap-3">
        <p className="text-ax-text-secondary m-0 text-xs">{hint}</p>
        {question.multiSelect && (
          <Button
            variant="primary"
            size="sm"
            label={t("chat_question_send")}
            icon={<ArrowUp aria-hidden="true" className="size-4" />}
            isDisabled={!canSend}
            isLoading={sending}
            isInterruptible
            onClick={send}
          />
        )}
      </div>
    </section>
  );
}
