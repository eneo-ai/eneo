"use client";

import { Button } from "@astryxdesign/core/Button";
import {
  ChatComposer,
  ChatComposerDrawer,
  type ChatComposerInputHandle,
  type ChatComposerToken,
  type ChatComposerTrigger
} from "@astryxdesign/core/Chat";
import { useMergedRefs } from "@astryxdesign/core/hooks";
import { Popover } from "@astryxdesign/core/Popover";
import {
  ArrowUp,
  BookOpen,
  ChevronDown,
  Folder,
  Globe,
  Plus,
  ShieldCheck,
  Square,
  TextQuote,
  X
} from "lucide-react";
import { useTranslations } from "next-intl";
import {
  useEffect,
  useId,
  useImperativeHandle,
  useRef,
  useState,
  type DragEvent,
  type KeyboardEvent,
  type ReactNode,
  type Ref
} from "react";
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
 * element itself for focus rescue. The field is an Astryx ChatComposerInput
 * (a contenteditable element), so there is no textarea to hold.
 */
export type ComposerHandle = {
  focus: () => void;
  element: HTMLElement | null;
  /** Puts text at the caret, as typed: a trigger character opens its menu. */
  insertText: (text: string) => void;
  /** Puts a token (a pill) at the caret, as a menu pick does. */
  insertToken: (token: ChatComposerToken) => void;
};

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
 * context. Enter sends and Shift+Enter adds a line (the hint is in its
 * description); an IME's Enter commits its candidate instead. Pasted or
 * dropped files become attachments and Backspace in an empty field removes
 * the last attachment. Message history and paste-as-token are off: a chat
 * draft is the person's own text. With `triggers`, typing their character
 * opens a menu whose picks become inline tokens (the flow chat's references).
 */
function ComposerInput({
  label,
  hintId,
  placeholder,
  onEnter,
  onPasteFiles,
  onBackspaceEmpty,
  minRows,
  triggers,
  ref
}: {
  label: string;
  hintId: string;
  placeholder: string;
  onEnter: () => void;
  onPasteFiles: (files: File[]) => void;
  onBackspaceEmpty: () => void;
  minRows: 1 | 2;
  triggers?: ChatComposerTrigger[];
  ref?: Ref<ComposerHandle>;
}) {
  const handle = useRef<ChatComposerInputHandle>(null);
  const root = useRef<HTMLDivElement>(null);
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
    if (event.key === "Enter" && !event.shiftKey) {
      // Astryx leaves an IME's Enter alone; so does this.
      if (event.nativeEvent.isComposing) return;
      // Sending is the page's: a blocked send keeps the text (Astryx's own
      // Enter would clear the field first).
      event.preventDefault();
      onEnter();
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
      aria-describedby={hintId}
      placeholder={placeholder}
      hasHistory={false}
      pasteAsToken={false}
      onFiles={onPasteFiles}
      onKeyDown={onKeyDown}
      triggers={triggers}
      className={cn("py-0.5", minRows === 2 && "[&_[contenteditable]]:min-h-[2.75rem]")}
    />
  );
}

/** Tracks a file drag over the composer for drop feedback. */
function useFileDrop(onFiles: (files: File[]) => void, enabled: boolean) {
  const [dragging, setDragging] = useState(false);
  const depth = useRef(0);
  const hasFiles = (event: DragEvent) => event.dataTransfer?.types?.includes("Files") ?? false;

  return {
    dragging: enabled && dragging,
    handlers: enabled
      ? {
          onDragEnter: (event: DragEvent) => {
            if (!hasFiles(event)) return;
            event.preventDefault();
            depth.current += 1;
            setDragging(true);
          },
          onDragOver: (event: DragEvent) => {
            if (hasFiles(event)) event.preventDefault();
          },
          onDragLeave: (event: DragEvent) => {
            if (!hasFiles(event)) return;
            depth.current = Math.max(0, depth.current - 1);
            if (depth.current === 0) setDragging(false);
          },
          onDrop: (event: DragEvent) => {
            if (!hasFiles(event)) return;
            depth.current = 0;
            setDragging(false);
            // A drop on the text field itself is the field's (`onFiles`).
            if (event.defaultPrevented) return;
            event.preventDefault();
            const files = Array.from(event.dataTransfer.files ?? []);
            if (files.length > 0) onFiles(files);
          }
        }
      : {}
  };
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
  /** Sends the current value (the caller validates and clears). */
  onSubmit: () => void;
  canSubmit: boolean;
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
  canSubmit,
  busy,
  onStop,
  label,
  placeholder,
  attachments,
  onOpenFileDialog,
  knowledge = [],
  tools,
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
  const hintId = useId();
  // The field's handle as state, so a control above the field can be given it
  // while rendering (a ref must not be read then).
  const [input, setInput] = useState<ComposerHandle | null>(null);
  const inputRefs = useMergedRefs(inputRef, setInput);
  useEffect(() => {
    onInput?.(input);
  }, [input, onInput]);
  const canAttach = attachments.maxFiles !== 0;
  const { dragging, handlers } = useFileDrop(
    (files) => void attachments.addFiles(files),
    canAttach && attachments.canAddMore
  );
  const hasAttachments = attachments.attachments.length > 0;

  const send = () => {
    if (busy || !canSubmit) return;
    onSubmit();
  };

  return (
    // Toasts rise above the whole composer while focus is in it (toast-lift.ts),
    // so Send stays in view while the user types.
    <div className="group/composer flex w-full flex-col gap-2" data-clear-of-toasts="">
      <div className="relative" {...handlers}>
        <ChatComposer
          value={value}
          onChange={onChange}
          // Submission runs through `send` (the field's Enter and the send
          // button) so a blocked send never clears the field.
          onSubmit={send}
          onStop={onStop}
          isStopShown={busy}
          elevation="none"
          className={cn(
            "rounded-ax-chat [&>div:has([contenteditable])]:shadow-ax-med",
            variant === "start" && "[&>div:has([contenteditable])]:rounded-[1.375rem]"
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
            <ComposerInput
              ref={inputRefs}
              label={label}
              hintId={hintId}
              placeholder={placeholder}
              minRows={variant === "start" ? 2 : 1}
              triggers={triggers}
              onEnter={send}
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
              {mention}
              {footerActions}
            </div>
          }
          sendActions={modelSelector}
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
              isDisabled={!busy && !canSubmit}
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
