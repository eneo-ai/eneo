import { SendHorizontal } from "lucide-react";
import { useTranslations } from "next-intl";
import { forwardRef, useCallback, useImperativeHandle, useRef, type KeyboardEvent } from "react";

export type WidgetComposerHandle = {
  focus: () => void;
  /** Put back a question that never reached the server, unless something new was typed. */
  restore: (question: string) => void;
};

/**
 * The question field and its send button. Its own markup rather than the
 * Astryx composer: the widget is painted in the host organisation's colours
 * (the send button, the focus ring) and sits in a 400 px panel on someone
 * else's page, with 16 px input text so phones do not zoom and 44 px targets.
 */
export const WidgetComposer = forwardRef<
  WidgetComposerHandle,
  {
    placeholder: string;
    maxLength: number;
    disabled: boolean;
    busy: boolean;
    value: string;
    onChange: (value: string) => void;
    onSend: (question: string) => void;
    onEscape?: () => void;
  }
>(function WidgetComposer(
  { placeholder, maxLength, disabled, busy, value, onChange, onSend, onEscape },
  ref
) {
  const t = useTranslations();
  const textarea = useRef<HTMLTextAreaElement>(null);

  const resize = useCallback(() => {
    const element = textarea.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 160)}px`;
  }, []);

  useImperativeHandle(
    ref,
    () => ({
      focus: () => textarea.current?.focus(),
      restore: (question) => {
        if (value.trim()) return;
        onChange(question);
        requestAnimationFrame(resize);
      }
    }),
    [value, onChange, resize]
  );

  const canSend = !disabled && !busy && value.trim().length > 0;

  function submit() {
    const question = value.trim();
    if (!question || disabled || busy) return;
    onChange("");
    requestAnimationFrame(resize);
    onSend(question);
    // The send arrow disables itself once the text is gone; a keyboard user
    // who pressed it would otherwise be left on the page body.
    textarea.current?.focus();
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Escape" && onEscape) {
      onEscape();
      return;
    }
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <div className="widget-input flex flex-col gap-2">
      <form
        className="widget-composer bg-ax-surface flex items-end gap-2 border px-3 py-2"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <label className="sr-only" htmlFor="widget-question">
          {t("widget_input_label")}
        </label>
        <textarea
          id="widget-question"
          ref={textarea}
          value={value}
          rows={1}
          maxLength={maxLength}
          placeholder={placeholder}
          disabled={disabled}
          className="text-ax-text placeholder:text-ax-text-secondary max-h-40 min-h-11 flex-1 resize-none bg-transparent py-1 text-base leading-6 disabled:opacity-60"
          onChange={(event) => {
            onChange(event.target.value);
            resize();
          }}
          onKeyDown={onKeyDown}
        />
        <button
          type="submit"
          className="widget-send flex size-11 shrink-0 items-center justify-center rounded-full disabled:opacity-50"
          aria-label={t("widget_send")}
          disabled={!canSend}
        >
          <SendHorizontal className="size-5" aria-hidden="true" />
        </button>
      </form>
    </div>
  );
});
