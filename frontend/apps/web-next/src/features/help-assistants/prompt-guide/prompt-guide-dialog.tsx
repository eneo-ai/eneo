"use client";

import {
  Check,
  ChevronDown,
  CircleAlert,
  Copy,
  FileText,
  RefreshCw,
  SendHorizontal,
  Sparkles
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MessageResponse } from "@/components/ai-elements/message";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupTextarea
} from "@/components/ui/input-group";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { extractFinalPrompt } from "./extract-final-prompt";
import { extractStructuredQuestion, type PromptGuideQuestion } from "./extract-structured-question";
import {
  continuePromptGuideRun,
  startPromptGuideRun,
  updateHelperRunStatus,
  type HelperRunResponse
} from "./helper-runs";

type Turn = {
  id: string;
  role: "user" | "assistant";
  text: string;
  isStreaming: boolean;
};

type LastSend = {
  question: string;
  showUserTurn: boolean;
};

function PromptGuideContextCard({ text }: { text: string }) {
  const t = useTranslations();
  const [expanded, setExpanded] = useState(false);
  if (!text) return null;

  return (
    <div className="bg-muted/30 overflow-hidden rounded-md border">
      <button
        type="button"
        className="hover:bg-muted/70 flex w-full items-center gap-2 px-3 py-2 text-left transition-colors"
        aria-expanded={expanded}
        onClick={() => setExpanded((current) => !current)}
      >
        <FileText className="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
        <span className="flex-1 text-sm font-medium">{t("prompt_guide_current_prompt_label")}</span>
        <ChevronDown
          className={cn(
            "text-muted-foreground size-4 shrink-0 transition-transform",
            expanded && "rotate-180"
          )}
          aria-hidden="true"
        />
      </button>
      {expanded && (
        <div className="border-t px-3 py-2">
          <p className="text-muted-foreground max-h-32 overflow-y-auto text-xs whitespace-pre-wrap">
            {text}
          </p>
        </div>
      )}
    </div>
  );
}

function PromptGuideQuestionCard({
  question,
  disabled,
  onAnswer
}: {
  question: PromptGuideQuestion;
  disabled: boolean;
  onAnswer: (text: string) => void;
}) {
  const t = useTranslations();
  const [q] = useState(question);
  const [radioValue, setRadioValue] = useState("");
  const [checkedFlags, setCheckedFlags] = useState<boolean[]>(() => q.options.map(() => false));
  const [otherText, setOtherText] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);
  const idPrefix = useMemo(
    () => `pg-q-${q.header.replace(/\s+/g, "-").toLowerCase()}-${q.question.length}`,
    [q.header, q.question.length]
  );

  useEffect(() => {
    cardRef.current
      ?.querySelector<HTMLElement>("[data-slot=radio-group-item], [data-slot=checkbox], textarea")
      ?.focus();
  }, []);

  function setChecked(index: number, checked: boolean) {
    setCheckedFlags((current) => current.map((value, i) => (i === index ? checked : value)));
  }

  function pickedText(): string {
    const picked: string[] = [];
    if (q.multiSelect) {
      q.options.forEach((option, index) => {
        if (checkedFlags[index]) picked.push(option.label);
      });
    } else if (radioValue !== "") {
      const index = Number.parseInt(radioValue, 10);
      const option = Number.isFinite(index) ? q.options[index] : undefined;
      if (option) picked.push(option.label);
    }

    const other = otherText.trim();
    if (other.length > 0) picked.push(other);
    return picked.join(", ");
  }

  const canSubmit =
    !submitted &&
    !disabled &&
    (otherText.trim().length > 0 ||
      (q.multiSelect ? checkedFlags.some(Boolean) : radioValue.length > 0));

  function submit() {
    if (!canSubmit) return;
    setSubmitted(true);
    onAnswer(pickedText());
  }

  function handleTextareaKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <div
      ref={cardRef}
      className={cn(
        "bg-background rounded-md border p-4 transition-opacity",
        submitted && "opacity-60"
      )}
      aria-busy={submitted}
    >
      <div className="text-muted-foreground mb-1 text-xs font-medium uppercase">{q.header}</div>
      <div id={`${idPrefix}-title`} className="mb-3 text-sm font-medium">
        {q.question}
      </div>

      {q.options.length > 0 && q.multiSelect && (
        <fieldset
          className="flex flex-col gap-2"
          disabled={submitted}
          aria-labelledby={`${idPrefix}-title`}
        >
          <legend className="sr-only">{q.question}</legend>
          {q.options.map((option, index) => {
            const id = `${idPrefix}-opt-${index}`;
            return (
              <Label
                key={id}
                htmlFor={id}
                className="hover:bg-muted/70 flex cursor-pointer items-start gap-3 rounded-md p-2"
              >
                <Checkbox
                  id={id}
                  checked={checkedFlags[index] ?? false}
                  disabled={submitted}
                  className="mt-0.5"
                  onCheckedChange={(value) => setChecked(index, value === true)}
                />
                <span className="flex-1 text-sm">
                  <span className="block font-medium">{option.label}</span>
                  {option.description && (
                    <span className="text-muted-foreground block text-xs">
                      {option.description}
                    </span>
                  )}
                </span>
              </Label>
            );
          })}
        </fieldset>
      )}

      {q.options.length > 0 && !q.multiSelect && (
        <RadioGroup
          value={radioValue}
          disabled={submitted}
          aria-labelledby={`${idPrefix}-title`}
          onValueChange={(value) => {
            setRadioValue(value);
            setOtherText("");
          }}
        >
          {q.options.map((option, index) => {
            const id = `${idPrefix}-opt-${index}`;
            return (
              <Label
                key={id}
                htmlFor={id}
                className="hover:bg-muted/70 flex cursor-pointer items-start gap-3 rounded-md p-2"
              >
                <RadioGroupItem
                  id={id}
                  value={String(index)}
                  disabled={submitted}
                  className="mt-0.5"
                />
                <span className="flex-1 text-sm">
                  <span className="block font-medium">{option.label}</span>
                  {option.description && (
                    <span className="text-muted-foreground block text-xs">
                      {option.description}
                    </span>
                  )}
                </span>
              </Label>
            );
          })}
        </RadioGroup>
      )}

      {q.options.length === 0 ? (
        <div className="flex flex-col gap-2">
          <Label htmlFor={`${idPrefix}-other`} className="text-sm font-medium">
            {t("prompt_guide_question_free_answer_label")}
          </Label>
          <Textarea
            id={`${idPrefix}-other`}
            value={otherText}
            rows={3}
            disabled={submitted}
            placeholder={t("prompt_guide_question_free_answer_placeholder")}
            className="resize-none"
            onKeyDown={handleTextareaKeyDown}
            onChange={(event) => setOtherText(event.target.value)}
          />
          <Button
            type="button"
            size="sm"
            disabled={!canSubmit}
            onClick={submit}
            className="self-end"
          >
            {t("prompt_guide_question_send")}
          </Button>
        </div>
      ) : (
        <div className="mt-3">
          <Label htmlFor={`${idPrefix}-other`} className="text-muted-foreground mb-1 block text-xs">
            {t("prompt_guide_question_other_label")}
          </Label>
          <div className="flex items-stretch gap-2">
            <Input
              id={`${idPrefix}-other`}
              value={otherText}
              disabled={submitted}
              placeholder={t("prompt_guide_question_other_placeholder")}
              onChange={(event) => {
                setOtherText(event.target.value);
                if (!q.multiSelect) setRadioValue("");
              }}
            />
            <Button type="button" size="sm" disabled={!canSubmit} onClick={submit}>
              {t("prompt_guide_question_send")}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function PromptGuideConversation({
  turns,
  isStreaming,
  hasCapturedPrompt,
  onQuestionAnswer
}: {
  turns: Turn[];
  isStreaming: boolean;
  hasCapturedPrompt: boolean;
  onQuestionAnswer: (text: string) => void;
}) {
  const t = useTranslations();
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastTurnTextLength = turns.at(-1)?.text.length ?? 0;

  useEffect(() => {
    const element = scrollRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [turns.length, lastTurnTextLength]);

  return (
    <div
      ref={scrollRef}
      className="bg-muted/30 min-h-72 flex-1 overflow-y-auto rounded-md border p-4"
      aria-live="polite"
      aria-busy={isStreaming}
      aria-label={t("prompt_guide_streaming_announcement")}
    >
      {turns.length === 0 ? (
        <div
          className="text-muted-foreground flex h-full flex-col items-center justify-center gap-2 text-center text-sm"
          role="status"
        >
          <Spinner className="size-5" aria-hidden="true" />
          <p>{t("prompt_guide_analyzing")}</p>
        </div>
      ) : (
        <ul className="flex flex-col gap-4">
          {turns.map((turn, index) => (
            <li key={turn.id} className="text-sm">
              {turn.role === "user" ? (
                <div className="text-muted-foreground flex justify-end">
                  <div className="break-words whitespace-pre-wrap">{turn.text}</div>
                </div>
              ) : turn.isStreaming && turn.text.length === 0 ? (
                <div className="text-muted-foreground flex items-center gap-2" role="status">
                  <Spinner aria-hidden="true" />
                  {index === 0 && hasCapturedPrompt && <span>{t("prompt_guide_analyzing")}</span>}
                </div>
              ) : (
                <AssistantTurn
                  turn={turn}
                  isStreaming={isStreaming}
                  onQuestionAnswer={onQuestionAnswer}
                />
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AssistantTurn({
  turn,
  isStreaming,
  onQuestionAnswer
}: {
  turn: Turn;
  isStreaming: boolean;
  onQuestionAnswer: (text: string) => void;
}) {
  const t = useTranslations();
  const segment = extractStructuredQuestion(turn.text);

  return (
    <div className="flex flex-col gap-2">
      {segment.kind === "parsed" ? (
        <>
          {segment.proseBefore.trim() && <MessageResponse>{segment.proseBefore}</MessageResponse>}
          <PromptGuideQuestionCard
            question={segment.question}
            disabled={isStreaming}
            onAnswer={onQuestionAnswer}
          />
          {segment.proseAfter.trim() && <MessageResponse>{segment.proseAfter}</MessageResponse>}
        </>
      ) : segment.kind === "pending" ? (
        <>
          {segment.proseBefore.trim() && <MessageResponse>{segment.proseBefore}</MessageResponse>}
          <div
            className="text-muted-foreground flex items-center gap-2 text-xs italic"
            role="status"
          >
            <Spinner className="size-3.5" aria-hidden="true" />
            <span>{t("prompt_guide_question_thinking")}</span>
          </div>
        </>
      ) : (
        <MessageResponse>{turn.text}</MessageResponse>
      )}
      {turn.isStreaming && (
        <>
          <span className="sr-only">{t("prompt_guide_streaming_announcement")}</span>
          <span
            className="bg-primary ml-0.5 inline-block h-4 w-0.5 animate-pulse align-middle"
            aria-hidden="true"
          />
        </>
      )}
    </div>
  );
}

function PromptGuideFinalCard({
  prompt,
  disabled,
  onApply
}: {
  prompt: string;
  disabled: boolean;
  onApply: (text: string) => void;
}) {
  const t = useTranslations();
  const [copied, setCopied] = useState(false);

  async function copyToClipboard() {
    try {
      await navigator.clipboard.writeText(prompt);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="bg-muted/30 flex flex-wrap items-center gap-3 rounded-md border px-3 py-2.5">
      <div className="bg-secondary grid size-8 shrink-0 place-items-center rounded-full">
        <Sparkles className="text-primary size-4" aria-hidden="true" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium">{t("prompt_guide_final_prompt_label")}</div>
        <div className="text-muted-foreground text-xs">{t("prompt_guide_final_prompt_hint")}</div>
      </div>
      <Button type="button" variant="outline" size="sm" onClick={copyToClipboard}>
        {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
        {copied ? t("copied") : t("copy")}
      </Button>
      <Button type="button" size="sm" disabled={disabled} onClick={() => onApply(prompt)}>
        {t("prompt_guide_apply_button")}
      </Button>
    </div>
  );
}

function PromptGuideInput({
  value,
  disabled,
  onValueChange,
  onSubmit
}: {
  value: string;
  disabled: boolean;
  onValueChange: (value: string) => void;
  onSubmit: (text: string) => void;
}) {
  const t = useTranslations();
  const trimmed = value.trim();
  const canSend = !disabled && trimmed.length > 0;

  function submit() {
    if (!canSend) return;
    onValueChange("");
    onSubmit(trimmed);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <form
      className="contents"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <InputGroup>
        <InputGroupTextarea
          rows={2}
          value={value}
          disabled={disabled}
          placeholder={t("prompt_guide_input_placeholder")}
          aria-label={t("prompt_guide_input_placeholder")}
          className="max-h-40 min-h-12"
          onKeyDown={handleKeyDown}
          onChange={(event) => onValueChange(event.target.value)}
        />
        <InputGroupAddon align="block-end">
          <InputGroupButton
            type="submit"
            size="icon-sm"
            variant="default"
            className="ml-auto"
            disabled={!canSend}
            aria-label={t("prompt_guide_question_send")}
          >
            {disabled ? <Spinner /> : <SendHorizontal />}
          </InputGroupButton>
        </InputGroupAddon>
      </InputGroup>
    </form>
  );
}

export function PromptGuideDialog({
  open,
  onOpenChange,
  targetId,
  targetPrompt,
  hasUnsavedPromptChanges,
  onApply
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  targetId: string;
  targetPrompt: string;
  hasUnsavedPromptChanges: boolean;
  onApply: (text: string) => void;
}) {
  const t = useTranslations();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [inputText, setInputText] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [capturedPrompt, setCapturedPrompt] = useState("");
  const [lastSend, setLastSend] = useState<LastSend | null>(null);
  const [overwriteConfirmOpen, setOverwriteConfirmOpen] = useState(false);
  const [pendingApplyText, setPendingApplyText] = useState<string | null>(null);
  const runIdRef = useRef<string | null>(null);
  const activeAbortRef = useRef<AbortController | null>(null);
  const isStreamingRef = useRef(false);
  const didApplyRef = useRef(false);
  const wasOpenRef = useRef(false);
  const turnCounterRef = useRef(0);

  const setRunId = useCallback((runId: string | null) => {
    runIdRef.current = runId;
  }, []);

  const resetState = useCallback(() => {
    activeAbortRef.current?.abort();
    activeAbortRef.current = null;
    isStreamingRef.current = false;
    didApplyRef.current = false;
    setTurns([]);
    setInputText("");
    setRunId(null);
    setIsStreaming(false);
    setErrorMessage(null);
    setLastSend(null);
    setOverwriteConfirmOpen(false);
    setPendingApplyText(null);
  }, [setRunId]);

  const sendQuestion = useCallback(
    async (rawQuestion: string, options?: { showUserTurn?: boolean }) => {
      const question = rawQuestion.trim();
      if (!question || isStreamingRef.current) return;

      const showUserTurn = options?.showUserTurn ?? true;
      setLastSend({ question, showUserTurn });
      setErrorMessage(null);
      setIsStreaming(true);
      isStreamingRef.current = true;

      const controller = new AbortController();
      activeAbortRef.current = controller;
      const assistantTurnId = `assistant-${turnCounterRef.current++}`;

      setTurns((current) => [
        ...current,
        ...(showUserTurn
          ? [
              {
                id: `user-${turnCounterRef.current++}`,
                role: "user" as const,
                text: question,
                isStreaming: false
              }
            ]
          : []),
        { id: assistantTurnId, role: "assistant", text: "", isStreaming: true }
      ]);

      const appendAnswer = (chunk: HelperRunResponse) => {
        if (!runIdRef.current && chunk.run.id) setRunId(chunk.run.id);
        if (!chunk.answer) return;
        setTurns((current) =>
          current.map((turn) =>
            turn.id === assistantTurnId ? { ...turn, text: turn.text + chunk.answer } : turn
          )
        );
      };

      try {
        const activeRunId = runIdRef.current;
        const result = activeRunId
          ? await continuePromptGuideRun({
              runId: activeRunId,
              question,
              signal: controller.signal,
              onAnswer: appendAnswer
            })
          : await startPromptGuideRun({
              targetId,
              question,
              signal: controller.signal,
              onAnswer: appendAnswer
            });

        if (controller.signal.aborted) return;
        if (!runIdRef.current && result.run.id) setRunId(result.run.id);
        setTurns((current) =>
          current.map((turn) =>
            turn.id === assistantTurnId
              ? {
                  ...turn,
                  text: result.answer.length > 0 ? result.answer : turn.text,
                  isStreaming: false
                }
              : turn
          )
        );
      } catch (error) {
        if (controller.signal.aborted) return;
        console.error("Prompt Guide stream failed", error);
        setErrorMessage(t("prompt_guide_error_generic"));
        setTurns((current) =>
          current.map((turn) =>
            turn.id === assistantTurnId ? { ...turn, isStreaming: false } : turn
          )
        );
      } finally {
        if (activeAbortRef.current === controller) activeAbortRef.current = null;
        isStreamingRef.current = false;
        setIsStreaming(false);
      }
    },
    [setRunId, t, targetId]
  );

  useEffect(() => {
    if (open && !wasOpenRef.current) {
      resetState();
      const nextPrompt = targetPrompt.trim();
      setCapturedPrompt(nextPrompt);
      const primingQuestion =
        nextPrompt.length > 0
          ? t("prompt_guide_priming_with_prompt", { prompt: nextPrompt })
          : t("prompt_guide_priming_no_prompt");
      void sendQuestion(primingQuestion, { showUserTurn: false });
    } else if (!open && wasOpenRef.current) {
      const closingRunId = runIdRef.current;
      const didApply = didApplyRef.current;
      resetState();
      if (closingRunId && !didApply) {
        void updateHelperRunStatus(closingRunId, "abandoned").catch(() => {});
      }
    }

    wasOpenRef.current = open;
  }, [open, resetState, sendQuestion, t, targetPrompt]);

  const lastFinalAssistantText = useMemo(() => {
    for (let i = turns.length - 1; i >= 0; i--) {
      const turn = turns[i];
      if (turn?.role === "assistant" && !turn.isStreaming && turn.text.trim().length > 0) {
        return turn.text;
      }
    }
    return "";
  }, [turns]);
  const finalPrompt = extractFinalPrompt(lastFinalAssistantText);

  const latestAssistantTurn = useMemo(() => {
    for (let i = turns.length - 1; i >= 0; i--) {
      if (turns[i]?.role === "assistant") return turns[i] ?? null;
    }
    return null;
  }, [turns]);

  const needsFallbackInput = useMemo(() => {
    if (isStreaming || finalPrompt) return false;
    if (!latestAssistantTurn || latestAssistantTurn.isStreaming) return false;
    const segment = extractStructuredQuestion(latestAssistantTurn.text);
    return segment.kind === "none" || segment.kind === "invalid";
  }, [finalPrompt, isStreaming, latestAssistantTurn]);

  function retryLast() {
    if (!lastSend || isStreaming) return;
    const removeCount = lastSend.showUserTurn ? 2 : 1;
    setTurns((current) => current.slice(0, Math.max(0, current.length - removeCount)));
    setErrorMessage(null);
    void sendQuestion(lastSend.question, { showUserTurn: lastSend.showUserTurn });
  }

  function handleApply(text: string) {
    if (!text || isStreaming) return;
    if (hasUnsavedPromptChanges) {
      setPendingApplyText(text);
      setOverwriteConfirmOpen(true);
      return;
    }
    applyNow(text);
  }

  function applyNow(text: string) {
    didApplyRef.current = true;
    const runId = runIdRef.current;
    onApply(text);
    onOpenChange(false);
    if (runId) void updateHelperRunStatus(runId, "completed").catch(() => {});
  }

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="flex max-h-[85vh] flex-col gap-3 sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Sparkles className="text-primary size-5" aria-hidden="true" />
              {t("prompt_guide_dialog_title")}
            </DialogTitle>
            <DialogDescription>{t("prompt_guide_dialog_description")}</DialogDescription>
          </DialogHeader>

          <PromptGuideContextCard text={capturedPrompt} />

          <PromptGuideConversation
            turns={turns}
            isStreaming={isStreaming}
            hasCapturedPrompt={capturedPrompt.length > 0}
            onQuestionAnswer={(text) => void sendQuestion(text)}
          />

          {finalPrompt && !isStreaming && (
            <PromptGuideFinalCard
              prompt={finalPrompt}
              disabled={isStreaming}
              onApply={handleApply}
            />
          )}

          {errorMessage && (
            <div
              role="alert"
              className="border-destructive/30 bg-destructive/10 text-destructive flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-sm"
            >
              <span className="flex-1">{errorMessage}</span>
              {lastSend && (
                <Button type="button" variant="outline" size="sm" onClick={retryLast}>
                  <RefreshCw className="size-3.5" />
                  {t("prompt_guide_retry")}
                </Button>
              )}
            </div>
          )}

          {needsFallbackInput && (
            <>
              <div
                role="status"
                className="border-warning/30 bg-warning/10 text-warning flex items-start gap-2 rounded-md border px-3 py-2 text-xs"
              >
                <CircleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
                <span className="flex-1">{t("prompt_guide_warning_llm_off_format")}</span>
              </div>
              <PromptGuideInput
                value={inputText}
                disabled={isStreaming}
                onValueChange={setInputText}
                onSubmit={(text) => void sendQuestion(text)}
              />
            </>
          )}
        </DialogContent>
      </Dialog>

      <AlertDialog open={overwriteConfirmOpen} onOpenChange={setOverwriteConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("prompt_guide_apply_overwrite_title")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("prompt_guide_apply_overwrite_warning")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                setOverwriteConfirmOpen(false);
                if (pendingApplyText !== null) applyNow(pendingApplyText);
              }}
            >
              {t("prompt_guide_apply_button")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
