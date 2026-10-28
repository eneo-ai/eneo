import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { Check, ThumbsDown, ThumbsUp } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";
import { cn } from "@/lib/utils";

type Vote = 1 | -1;

/**
 * Thumbs on the conversation, the acknowledgement, and the opt-in comment
 * dialog. State is keyed by conversation id so a new conversation starts
 * clean while an earlier one keeps what the visitor already did; a restored
 * conversation shows the vote the server remembers. The chat keeps this
 * mounted across follow-up questions, so the state lives as long as the
 * conversation does.
 */
export function WidgetFeedback({
  sessionId,
  collectsText,
  restored = null,
  disabled = false,
  submit
}: {
  sessionId: string;
  /** The widget stores comments; without it only the thumbs are offered. */
  collectsText: boolean;
  /** The vote the server already holds for a restored conversation. */
  restored?: { value: Vote; text?: string | null } | null;
  /** While the next answer is on its way. */
  disabled?: boolean;
  /** Sends a vote (with an optional comment); resolves to the visitor-facing error, or null. */
  submit: (feedback: { value: Vote; text?: string }) => Promise<string | null>;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const formId = useId();
  const textId = useId();
  const [votes, setVotes] = useState<Record<string, Vote>>({});
  const [comments, setComments] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState(false);
  const [voting, setVoting] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  // Shown where the visitor is looking: inside the dialog while it is open,
  // otherwise under the thumbs. A toast would hide behind the overlay. A
  // failed feedback request belongs to that attempt: a new question owns
  // the next error location, so an error carries the generation it was made
  // in and only the current generation's error shows.
  const [generation, setGeneration] = useState(0);
  const [failure, setFailure] = useState<{ generation: number; message: string } | null>(null);
  const changeButton = useRef<HTMLButtonElement>(null);
  const helpfulButton = useRef<HTMLButtonElement>(null);
  const unhelpfulButton = useRef<HTMLButtonElement>(null);

  // A question on its way starts a generation and closes the vote editor.
  const [wasDisabled, setWasDisabled] = useState(disabled);
  if (disabled !== wasDisabled) {
    setWasDisabled(disabled);
    if (disabled) {
      setGeneration(generation + 1);
      setEditing(false);
    }
  }
  const error = failure && failure.generation === generation ? failure.message : null;
  const setError = (message: string | null) =>
    setFailure(message === null ? null : { generation, message });

  const given: Vote | undefined = votes[sessionId] ?? restored?.value ?? undefined;
  // A later vote keeps a stored comment (it is sent without text), so this
  // stays true across vote changes.
  const savedComment = comments[sessionId] ?? restored?.text ?? "";
  const sent = !!savedComment;

  function finishVoting() {
    setEditing(false);
    requestAnimationFrame(() => changeButton.current?.focus({ preventScroll: true }));
  }

  function changeVote() {
    const next = !editing;
    setEditing(next);
    if (next) {
      requestAnimationFrame(() =>
        (given === -1 ? unhelpfulButton : helpfulButton).current?.focus({ preventScroll: true })
      );
    }
  }

  async function vote(value: Vote) {
    if (voting || disabled) return;
    if (given === value) return finishVoting();
    setVoting(true);
    setError(null);
    try {
      // The error is stamped with this attempt's generation; a later question
      // hides it, and the focus move is skipped once the editor is gone.
      const problem = await submit({ value });
      setError(problem);
      if (!problem) {
        setVotes((state) => ({ ...state, [sessionId]: value }));
        announce(sent ? t("widget_feedback_received") : t("widget_feedback_thanks"));
        finishVoting();
      }
    } finally {
      setVoting(false);
    }
  }

  async function sendComment() {
    const value = given;
    const comment = text.trim();
    if (!value || !comment || sending) return;
    setSending(true);
    setError(null);
    try {
      const problem = await submit({ value, text: comment });
      setError(problem);
      if (!problem) {
        setComments((state) => ({ ...state, [sessionId]: comment }));
        setText("");
        setDialogOpen(false);
        announce(t("widget_feedback_received"));
      }
    } finally {
      setSending(false);
    }
  }

  function openDialog() {
    setText(savedComment);
    setError(null);
    setDialogOpen(true);
  }

  const thumb = (value: Vote, ref: typeof helpfulButton, label: string, Icon: typeof ThumbsUp) => (
    <button
      type="button"
      ref={ref}
      className={cn(
        "flex min-h-11 min-w-11 items-center justify-center rounded-full disabled:opacity-50",
        given === value
          ? "bg-ax-accent-muted text-ax-text-accent"
          : "text-ax-text-secondary hover:bg-ax-hover"
      )}
      aria-label={label}
      aria-pressed={given === value}
      disabled={disabled}
      onClick={() => void vote(value)}
    >
      <Icon className="size-4" aria-hidden="true" />
    </button>
  );

  return (
    <>
      {(!given || editing) && (
        <div
          className="mt-3 flex items-center gap-2"
          role="group"
          aria-labelledby="widget-feedback-prompt"
        >
          <span id="widget-feedback-prompt" className="text-ax-text-secondary text-xs">
            {t("widget_feedback_prompt")}
          </span>
          {thumb(1, helpfulButton, t("widget_feedback_helpful"), ThumbsUp)}
          {thumb(-1, unhelpfulButton, t("widget_feedback_unhelpful"), ThumbsDown)}
        </div>
      )}
      {given && (
        <>
          {/* The acknowledgement is announced when the vote lands; a restored
              vote is shown without being announced. */}
          <p className="widget-enter text-ax-text-secondary mt-2 flex items-center gap-1.5 text-xs">
            <Check className="text-ax-green size-3.5 shrink-0" aria-hidden="true" />
            {sent ? t("widget_feedback_received") : t("widget_feedback_thanks")}
          </p>
          <div className="widget-enter flex flex-wrap items-center gap-x-3">
            <button
              type="button"
              ref={changeButton}
              className="text-ax-text-accent min-h-11 rounded-md text-xs underline-offset-2 hover:underline disabled:opacity-50"
              aria-expanded={editing}
              disabled={disabled}
              onClick={changeVote}
            >
              {t("widget_feedback_change")}
            </button>
            {collectsText && (
              <button
                type="button"
                className="text-ax-text-accent min-h-11 w-fit rounded-md text-xs underline-offset-2 hover:underline disabled:opacity-50"
                disabled={disabled}
                onClick={openDialog}
              >
                {sent
                  ? t("widget_feedback_edit_comment")
                  : given === -1
                    ? t("widget_feedback_more_negative")
                    : t("widget_feedback_more")}
              </button>
            )}
          </div>
        </>
      )}
      {error && !dialogOpen && (
        <p role="alert" className="bg-ax-error-muted text-ax-red mt-2 rounded-lg px-3 py-2 text-xs">
          {error}
        </p>
      )}

      <Dialog isOpen={dialogOpen} onOpenChange={setDialogOpen} purpose="form" width={420}>
        <Layout
          height="auto"
          header={
            <DialogHeader title={t("widget_feedback_more_title")} onOpenChange={setDialogOpen} />
          }
          content={
            <LayoutContent>
              <form
                id={formId}
                className="flex flex-col gap-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  void sendComment();
                }}
              >
                <p className="text-ax-text-secondary text-sm">{t("widget_feedback_more_body")}</p>
                <label className="sr-only" htmlFor={textId}>
                  {t("widget_feedback_more_title")}
                </label>
                <textarea
                  id={textId}
                  className="border-ax-border-control bg-ax-surface text-ax-text w-full resize-y rounded-lg border px-3 py-2 text-sm"
                  rows={4}
                  maxLength={2000}
                  placeholder={
                    given === -1
                      ? t("widget_feedback_more_placeholder_negative")
                      : t("widget_feedback_more_placeholder")
                  }
                  value={text}
                  onChange={(event) => setText(event.target.value)}
                />
                {error && dialogOpen && (
                  <p
                    role="alert"
                    className="bg-ax-error-muted text-ax-red rounded-lg px-3 py-2 text-sm"
                  >
                    {error}
                  </p>
                )}
              </form>
            </LayoutContent>
          }
          footer={
            <LayoutFooter>
              <div className="flex flex-wrap justify-end gap-2">
                <Button label={t("cancel")} onClick={() => setDialogOpen(false)} />
                {/* Keeps focus while sending: a disabled button would drop it. */}
                <Button
                  type="submit"
                  form={formId}
                  variant="primary"
                  label={sending ? t("widget_feedback_sending") : t("widget_feedback_send")}
                  isDisabled={!text.trim()}
                  isLoading={sending}
                  isInterruptible
                />
              </div>
            </LayoutFooter>
          }
        />
      </Dialog>
    </>
  );
}
