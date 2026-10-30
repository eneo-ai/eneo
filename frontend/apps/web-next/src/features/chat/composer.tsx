"use client";

import { Button } from "@astryxdesign/core/Button";
import {
  ChatComposer,
  ChatComposerDrawer,
  useChatComposerContext,
  type ChatComposerInputHandle,
  type ChatComposerToken,
  type ChatComposerTrigger
} from "@astryxdesign/core/Chat";
import { useAnnounce, useMergedRefs } from "@astryxdesign/core/hooks";
import { Kbd } from "@astryxdesign/core/Kbd";
import { Popover } from "@astryxdesign/core/Popover";
import {
  ArrowUp,
  BookOpen,
  ChevronDown,
  CircleAlert,
  Folder,
  Globe,
  Plus,
  ShieldCheck,
  Square,
  TextQuote,
  X
} from "lucide-react";
import { useTranslations } from "use-intl";
import {
  useEffect,
  useId,
  useImperativeHandle,
  useRef,
  useState,
  type ClipboardEvent,
  type KeyboardEvent,
  type ReactNode,
  type Ref
} from "react";
import { useFileDrop } from "@/features/files/use-file-drop";
import { revealProblems } from "@/components/composites/field-problem";
import { ChatComposerInput } from "@/components/astryx/chat-composer-input";
import type { ComposerInsert } from "./chat-references";
import type { KnowledgeOrigin } from "@/lib/chat/types";
import { cn } from "@/lib/utils";
import { ComposerAttachments } from "./attachments";
import { tableQuoteSummary } from "./side-panel/question-quote";
import type { useAttachments } from "./use-attachments";

type Attachments = ReturnType<typeof useAttachments>;

/** Shared look of the composer's pill buttons (attach, knowledge). */
const PILL_CLASS =
  "focus-visible:outline-ring inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-[13px] font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:text-ax-text-disabled pointer-coarse:h-11 pointer-coarse:min-w-11";
const PILL_ACTIVE_CLASS = "bg-ax-accent-muted text-ax-text-accent";

/**
 * What a page holds of the composer's text field: a way to focus it, and the
 * element itself for focus rescue, for both the textarea and reference input.
 */
export type ComposerHandle = {
  focus: () => void;
  element: HTMLElement | null;
  /** Puts text at the caret, as typed: a trigger character opens its menu. */
  insertText: (text: string) => void;
  /** Puts a token (a pill) at the caret, as a menu pick does. */
  insertToken: (token: ChatComposerToken) => void;
};

/**
 * The composer's text field. A real <textarea> (e2e and assistive tech rely
 * on it) wired to Astryx ChatComposer's context. Return adds a line, as in
 * any text field, and ⌘ or Ctrl+Return sends (decision 3: a half-written
 * question is never sent by accident); the hint is in its description. IME
 * composition is respected, pasted files become attachments and Backspace in
 * an empty field removes the last attachment.
 */
function ComposerTextarea({
  label,
  describedBy,
  invalid,
  placeholder,
  onSend,
  onPasteFiles,
  onBackspaceEmpty,
  rows,
  ref
}: {
  label: string;
  describedBy: string;
  invalid: boolean;
  placeholder: string;
  onSend: () => void;
  onPasteFiles: (files: File[]) => void;
  onBackspaceEmpty: () => void;
  rows: number;
  ref?: Ref<ComposerHandle>;
}) {
  const composer = useChatComposerContext();
  const field = useRef<HTMLTextAreaElement>(null);
  const onChange = useRef(composer?.onChange);
  useEffect(() => {
    onChange.current = composer?.onChange;
  });
  useImperativeHandle(ref, () => {
    const insertText = (text: string) => {
      const element = field.current;
      if (!element) return;
      element.focus();
      element.setRangeText(text, element.selectionStart, element.selectionEnd, "end");
      onChange.current?.(element.value);
    };
    return {
      focus: () => field.current?.focus(),
      get element() {
        return field.current;
      },
      insertText,
      insertToken: (token) => insertText(token.value)
    };
  }, []);
  const [composing, setComposing] = useState(false);

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      if (composing || event.nativeEvent.isComposing) return;
      event.preventDefault();
      onSend();
      return;
    }
    if (event.key === "Backspace" && event.currentTarget.value === "") {
      onBackspaceEmpty();
    }
  };

  const onPaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const files: File[] = [];
    for (const item of event.clipboardData?.items ?? []) {
      if (item.kind === "file") {
        const file = item.getAsFile();
        if (file) files.push(file);
      }
    }
    if (files.length > 0) {
      event.preventDefault();
      onPasteFiles(files);
    }
  };

  return (
    <textarea
      ref={field}
      name="message"
      rows={rows}
      value={composer?.value ?? ""}
      onChange={(event) => composer?.onChange(event.currentTarget.value)}
      onKeyDown={onKeyDown}
      onPaste={onPaste}
      onCompositionStart={() => setComposing(true)}
      onCompositionEnd={() => setComposing(false)}
      aria-label={label}
      aria-describedby={describedBy}
      aria-invalid={invalid || undefined}
      placeholder={placeholder}
      // The Astryx ChatComposer around this textarea draws the 3:1 focus ring
      // (focus-within), so the field itself has none.
      // eslint-disable-next-line eneo/no-weak-focus-indicator -- ring drawn by ChatComposer
      className="text-ax-text placeholder:text-ax-text-secondary block [field-sizing:content] max-h-[min(12rem,30dvh)] min-h-[46px] w-full resize-none bg-transparent px-1.5 py-0.5 text-base leading-normal focus:outline-none"
    />
  );
}

const isToken = (node: Node | null): node is HTMLElement =>
  node instanceof HTMLElement && node.hasAttribute("data-astryx-token");
const isBlank = (node: Node | null): node is Text =>
  node?.nodeType === Node.TEXT_NODE && /^[  ]?$/.test(node.textContent ?? "");

/**
 * Removes the token (a pill) just before a collapsed caret, with the blank
 * Astryx keeps after it. One Backspace takes the pill; Astryx's own handling
 * only takes the blank first, which looks like nothing happened. False when
 * the caret is not right after a token.
 */
function removeTokenBeforeCaret(editable: HTMLElement): boolean {
  const selection = window.getSelection();
  if (!selection?.rangeCount || !selection.isCollapsed) return false;
  const { startContainer: node, startOffset: offset } = selection.getRangeAt(0);
  if (!editable.contains(node)) return false;
  let before: Node | null;
  if (node.nodeType === Node.TEXT_NODE) {
    // At the start of a text, or at the end of the blank after a token.
    if (offset === 0) before = node.previousSibling;
    else if (isBlank(node) && offset === (node.textContent?.length ?? 0)) before = node;
    else return false;
  } else if (node === editable) {
    before = editable.childNodes[offset - 1] ?? null;
  } else {
    return false;
  }
  const blank = isBlank(before) ? before : null;
  const token = blank ? blank.previousSibling : before;
  if (!isToken(token)) return false;
  blank?.remove();
  token.remove();
  return true;
}

/**
 * The composer's text field: Astryx ChatComposerInput on ChatComposer's
 * context. Ctrl/⌘+Enter sends; Enter adds a line. An IME's Enter
 * commits its candidate instead. Pasted or
 * dropped files become attachments and Backspace in an empty field removes
 * the last attachment. Message history and paste-as-token are off: a chat
 * draft is the person's own text. With `triggers`, typing their character
 * opens a menu whose picks become inline tokens (the flow chat's references).
 */
function ComposerInput({
  label,
  describedBy,
  invalid,
  placeholder,
  onSend,
  onPasteFiles,
  onBackspaceEmpty,
  minRows,
  triggers,
  ref
}: {
  label: string;
  describedBy: string;
  invalid: boolean;
  placeholder: string;
  onSend: () => void;
  onPasteFiles: (files: File[]) => void;
  onBackspaceEmpty: () => void;
  minRows: 1 | 2;
  triggers?: ChatComposerTrigger[];
  ref?: Ref<ComposerHandle>;
}) {
  const handle = useRef<ChatComposerInputHandle>(null);
  const root = useRef<HTMLDivElement>(null);
  const composing = useRef(false);
  useImperativeHandle(
    ref,
    () => ({
      focus: () => handle.current?.focus(),
      get element() {
        return root.current?.querySelector<HTMLElement>("[contenteditable]") ?? null;
      },
      insertToken: (token) => {
        handle.current?.focus();
        handle.current?.insertToken(token);
        // Astryx's menu emits the change after its own insert; the public
        // insert does not, so the field would keep its placeholder and the
        // page its old value.
        root.current
          ?.querySelector("[contenteditable]")
          ?.dispatchEvent(new Event("input", { bubbles: true }));
      },
      insertText: (text) => {
        const editable = root.current?.querySelector<HTMLElement>("[contenteditable]");
        handle.current?.focus();
        handle.current?.insertText(text);
        if (!editable) return;
        // Astryx reads the text before the caret from the text node the
        // caret is in; a programmatic insert can leave the caret between
        // nodes instead. Put it at the end of the text just written.
        const selection = window.getSelection();
        const range = selection?.rangeCount ? selection.getRangeAt(0) : null;
        if (selection && range?.collapsed && range.startContainer === editable) {
          const node = editable.childNodes[range.startOffset - 1];
          if (node?.nodeType === Node.TEXT_NODE) {
            const caret = document.createRange();
            caret.setStart(node, node.textContent?.length ?? 0);
            caret.collapse(true);
            selection.removeAllRanges();
            selection.addRange(caret);
          }
        }
        // Astryx opens a trigger menu from the input event, not from the insert.
        editable.dispatchEvent(new Event("input", { bubbles: true }));
      }
    }),
    []
  );

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    // An open trigger menu has taken its keys before this runs.
    if (event.key === "Enter") {
      // Astryx leaves an IME's Enter alone; so does this.
      if (event.nativeEvent.isComposing) return;
      if (composing.current) {
        // Astryx submits when the browser omits isComposing on the final key.
        event.preventDefault();
        return;
      }
      // Sending is the page's: a blocked send keeps the text (Astryx's own
      // Enter would clear the field first).
      event.preventDefault();
      if (event.metaKey || event.ctrlKey) {
        onSend();
      } else {
        handle.current?.insertText("\n");
        root.current
          ?.querySelector("[contenteditable]")
          ?.dispatchEvent(new Event("input", { bubbles: true }));
      }
      return;
    }
    if (event.key === "Backspace") {
      const editable = root.current?.querySelector<HTMLElement>("[contenteditable]");
      if (editable && removeTokenBeforeCaret(editable)) {
        event.preventDefault();
        // Astryx emits the change and drops the token's portal on input.
        editable.dispatchEvent(new Event("input", { bubbles: true }));
        return;
      }
      if ((handle.current?.getValue() ?? "") === "") onBackspaceEmpty();
    }
  };

  return (
    <ChatComposerInput
      ref={root}
      handleRef={handle}
      label={label}
      aria-describedby={describedBy}
      aria-invalid={invalid || undefined}
      placeholder={placeholder}
      hasHistory={false}
      pasteAsToken={false}
      onFiles={onPasteFiles}
      onKeyDown={onKeyDown}
      onCompositionStart={() => {
        composing.current = true;
      }}
      onCompositionEnd={() => {
        composing.current = false;
      }}
      triggers={triggers}
      className={cn("py-0.5", minRows === 2 && "[&_[contenteditable]]:min-h-[2.75rem]")}
    />
  );
}

/**
 * "Kunskap: <källa>" pill for partners with knowledge attached. Knowledge is
 * always searched (there is no per-message switch in the backend), so this is
 * not a toggle: it opens a list of the collections and websites the answer
 * draws on.
 */
function KnowledgePill({ knowledge }: { knowledge: KnowledgeOrigin[] }) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const first = knowledge[0];
  if (!first) return null;
  const more = knowledge.length - 1;
  return (
    <Popover
      isOpen={open}
      onOpenChange={setOpen}
      placement="above"
      label={t("chat_knowledge_popover_label")}
      closeButtonLabel={t("close")}
      width={288}
      content={
        <div className="flex flex-col gap-2 p-1">
          <p className="text-ax-text-secondary text-xs">{t("chat_knowledge_popover_hint")}</p>
          <ul className="flex flex-col gap-1">
            {knowledge.map((origin) => {
              const Icon = origin.kind === "website" ? Globe : Folder;
              return (
                <li key={origin.id} className="flex min-w-0 items-center gap-2 text-[13px]">
                  <Icon aria-hidden="true" className="text-ax-text-secondary size-3.5 shrink-0" />
                  <span className="truncate">{origin.name}</span>
                </li>
              );
            })}
          </ul>
        </div>
      }
    >
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        className={cn(PILL_CLASS, PILL_ACTIVE_CLASS, "max-w-[14rem]")}
      >
        <BookOpen aria-hidden="true" className="size-[15px] shrink-0" />
        <span className="truncate max-sm:sr-only">
          {t("chat_knowledge_pill", { name: first.name })}
          {more > 0 ? ` +${more}` : ""}
        </span>
        <ChevronDown aria-hidden="true" className="size-3.5 shrink-0" />
      </button>
    </Popover>
  );
}

export type ComposerProps = {
  value: string;
  onChange: (value: string) => void;
  /** Sends the current value (the caller clears it). Never called with an empty draft. */
  onSubmit: () => void;
  /**
   * Why the question cannot be sent now, besides an empty draft (the context
   * is full). Shown at the field and announced when the user tries; Send
   * stays enabled (ACCESSIBILITY.md, forms).
   */
  sendBlocked?: string | null;
  busy: boolean;
  onStop: () => void;
  /** Persistent accessible name of the text field. */
  label: string;
  placeholder: string;
  attachments: Attachments;
  onOpenFileDialog: () => void;
  knowledge?: KnowledgeOrigin[];
  /** Verktyg pill: the popover with a switch per capability and MCP server. */
  tools?: ReactNode;
  /** Personal chat: the Skills pill beside Verktyg. */
  skills?: ReactNode;
  /** Group chats: @-mention picker. */
  mention?: ReactNode;
  /** Personal assistant: model picker on the right. */
  modelSelector?: ReactNode;
  /** Start state for the personal assistant: the assistant selector as a token. */
  partnerToken?: ReactNode;
  /** Context-usage bar, shown under the composer. */
  contextBar?: ReactNode;
  /** A passage quoted from a file or a view, sent as the opening lines of the question. */
  quote?: ComposerQuote | null;
  /** Menus the text field opens as their character is typed (the flow chat's references). */
  triggers?: ChatComposerTrigger[];
  /**
   * Small icon-only buttons above the text field. A function gets a way to
   * put text in the field (a "Referera" button that types "@").
   */
  headerActions?: ReactNode | ((input: ComposerInsert) => ReactNode);
  /** Controls after the pills in the footer (the flow chat's Fråga/Redigera picker). */
  footerActions?: ReactNode;
  variant?: "docked" | "start";
  inputRef?: Ref<ComposerHandle>;
  /** The field as something to insert into, while it is on screen. */
  onInput?: (input: ComposerInsert | null) => void;
};

export type ComposerQuote = {
  text: string;
  /** Where the text is from: the file, or what the view shows. */
  source: string;
  onRemove: () => void;
};

/** The quote waiting in the composer's drawer, with where it is from and a way to drop it. */
function ComposerQuoteCard({ quote }: { quote: ComposerQuote }) {
  const t = useTranslations();
  // No room for a quoted table itself here: its columns and size stand in.
  const table = tableQuoteSummary(quote.text);
  return (
    <div
      role="group"
      aria-label={t("chat_quote_label")}
      className="border-ax-accent bg-ax-surface rounded-ax-element flex items-start gap-2.5 border-s-2 py-2 ps-3 pe-1"
    >
      <TextQuote aria-hidden="true" className="text-ax-text-secondary mt-0.5 size-4 shrink-0" />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        {table ? (
          <>
            <p className="truncate text-[13.5px] leading-snug">{table.columns.join(" · ")}</p>
            <p className="text-ax-text-secondary text-xs">
              {table.rows === 1
                ? t("file_quote_table_row")
                : t("file_quote_table_rows", { count: table.rows })}
            </p>
          </>
        ) : (
          <p className="line-clamp-3 text-[13.5px] leading-snug whitespace-pre-wrap">
            {quote.text}
          </p>
        )}
        <p className="text-ax-text-secondary truncate text-xs">{quote.source}</p>
      </div>
      <button
        type="button"
        aria-label={t("chat_quote_remove")}
        onClick={quote.onRemove}
        className="text-ax-text-secondary hover:bg-ax-hover hover:text-ax-text focus-visible:outline-ring rounded-ax-element flex size-7 shrink-0 items-center justify-center focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:size-11"
      >
        <X className="size-3.5" aria-hidden="true" />
      </button>
    </div>
  );
}

/**
 * The chat composer (Astryx ChatComposer): drawer with attachment cards,
 * the text field, and a row with attach, the knowledge pill (accent tint,
 * clearly lighter than Send), tools, the model picker and send/stop. Files
 * can be dropped anywhere on it; the attach button is the non-drag
 * alternative (WCAG 2.5.7). Footer: data-sovereignty note.
 */
export function Composer({
  value,
  onChange,
  onSubmit,
  sendBlocked = null,
  busy,
  onStop,
  label,
  placeholder,
  attachments,
  onOpenFileDialog,
  knowledge = [],
  tools,
  skills,
  mention,
  modelSelector,
  partnerToken,
  contextBar,
  quote = null,
  triggers,
  headerActions,
  footerActions,
  variant = "docked",
  inputRef,
  onInput
}: ComposerProps) {
  const t = useTranslations();
  const announce = useAnnounce();
  const hintId = useId();
  const problemId = useId();
  const [problem, setProblem] = useState<string | null>(null);
  // The field's handle as state, so a control above the field can be given it
  // while rendering (a ref must not be read then).
  const [input, setInput] = useState<ComposerHandle | null>(null);
  const inputRefs = useMergedRefs(inputRef, setInput);
  useEffect(() => {
    onInput?.(input);
  }, [input, onInput]);
  const tokenInput = triggers !== undefined;
  const Input = tokenInput ? ComposerInput : ComposerTextarea;
  const canAttach = attachments.maxFiles !== 0;
  const { dragging, handlers } = useFileDrop((files) => void attachments.addFiles(files), {
    enabled: canAttach && attachments.canAddMore
  });
  const hasAttachments = attachments.attachments.length > 0;

  const change = (next: string) => {
    setProblem(null);
    onChange(next);
  };

  // Send is never disabled (decision 44): an attempt that cannot go says why
  // at the field, out loud, and leaves focus there to fix it.
  const send = () => {
    if (busy) return;
    const missing = value.trim() === "" ? t("chat_composer_empty") : sendBlocked;
    if (missing) {
      // Rendered first, so the field is read with its new description.
      revealProblems(() => setProblem(missing), input?.element ?? null);
      announce(missing);
      return;
    }
    setProblem(null);
    onSubmit();
  };

  return (
    // Toasts rise above the whole composer while focus is in it (toast-lift.ts),
    // so Send stays in view while the user types.
    <div className="group/composer flex w-full flex-col gap-2" data-clear-of-toasts="">
      <div className="relative" {...handlers}>
        <ChatComposer
          value={value}
          onChange={change}
          // Submission runs through `send` (the field's ⌘/Ctrl+Return and
          // the send button) so a blocked send never clears the field.
          onSubmit={send}
          onStop={onStop}
          isStopShown={busy}
          elevation="none"
          className={cn(
            "rounded-ax-chat [&>div:has(textarea,[contenteditable])]:shadow-ax-med",
            variant === "start" && "[&>div:has(textarea,[contenteditable])]:rounded-[1.375rem]"
          )}
          drawer={
            hasAttachments || quote ? (
              <ChatComposerDrawer label={t("attachments")}>
                <div className="flex w-full flex-col gap-2">
                  {quote && <ComposerQuoteCard quote={quote} />}
                  {hasAttachments && <ComposerAttachments attachments={attachments} />}
                </div>
              </ChatComposerDrawer>
            ) : undefined
          }
          headerActions={
            typeof headerActions === "function"
              ? input
                ? headerActions(input)
                : null
              : headerActions
          }
          input={
            <Input
              ref={inputRefs}
              label={label}
              describedBy={problem ? `${problemId} ${hintId}` : hintId}
              invalid={problem !== null}
              placeholder={placeholder}
              minRows={variant === "start" ? 2 : 1}
              rows={variant === "start" ? 2 : 1}
              triggers={triggers}
              onSend={send}
              onPasteFiles={(files) => void attachments.addFiles(files)}
              onBackspaceEmpty={() => {
                const last = attachments.attachments.at(-1);
                if (last) attachments.removeAttachment(last.key);
              }}
            />
          }
          footerActions={
            <div className="flex min-w-0 flex-wrap items-center gap-1">
              {partnerToken}
              {canAttach && (
                <button
                  type="button"
                  aria-label={t("chat_attach_files")}
                  disabled={!attachments.canAddMore}
                  onClick={onOpenFileDialog}
                  className={cn(
                    PILL_CLASS,
                    "border-ax-border-control text-ax-text-secondary hover:bg-ax-hover hover:text-ax-text size-8 justify-center border px-0 pointer-coarse:size-11"
                  )}
                >
                  <Plus aria-hidden="true" className="size-4" />
                </button>
              )}
              <KnowledgePill knowledge={knowledge} />
              {tools}
              {skills}
              {mention}
              {footerActions}
            </div>
          }
          sendActions={
            <>
              {modelSelector}
              {/* The shortcut beside the button it stands for, where there is a
                  keyboard to press it; the field's description says it in words. */}
              <span aria-hidden="true" className="hidden pointer-fine:inline-flex">
                <Kbd keys="mod+enter" />
              </span>
            </>
          }
          sendButton={
            <Button
              label={busy ? t("stop_generating") : t("send_message")}
              isIconOnly
              variant="primary"
              icon={
                busy ? (
                  <Square aria-hidden="true" className="size-3.5 fill-current" />
                ) : (
                  <ArrowUp aria-hidden="true" className="size-[17px]" strokeWidth={2.3} />
                )
              }
              onClick={busy ? onStop : send}
              className="size-[34px] shrink-0 rounded-full pointer-coarse:size-11"
            />
          }
        />
        {dragging && (
          <div
            aria-hidden="true"
            className="border-ax-accent bg-ax-accent-muted text-ax-text-accent rounded-ax-chat pointer-events-none absolute inset-0 z-10 flex items-center justify-center border-2 border-dashed text-sm font-semibold"
          >
            {t("chat_drop_files")}
          </div>
        )}
      </div>
      {problem && (
        <p id={problemId} className="text-ax-error flex items-center gap-1.5 px-1 text-xs">
          <CircleAlert aria-hidden="true" className="size-3.5 shrink-0" />
          {problem}
        </p>
      )}
      <span id={hintId} className="sr-only">
        {t("chat_composer_hint")}
      </span>
      {contextBar}
      <p className="text-ax-text-secondary flex items-center justify-center gap-1.5 text-center text-xs">
        <ShieldCheck aria-hidden="true" className="size-3.5 shrink-0" />
        {variant === "start" ? t("chat_sovereignty_hint") : t("chat_sovereignty_hint_full")}
      </p>
    </div>
  );
}
