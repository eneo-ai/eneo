"use client";

import { Button } from "@astryxdesign/core/Button";
import { ChatComposer, ChatComposerDrawer, useChatComposerContext } from "@astryxdesign/core/Chat";
import { Popover } from "@astryxdesign/core/Popover";
import { Tooltip } from "@astryxdesign/core/Tooltip";
import {
  ArrowUp,
  BookOpen,
  ChevronDown,
  Folder,
  Globe,
  Plus,
  ShieldCheck,
  Square,
  type LucideIcon
} from "lucide-react";
import { useTranslations } from "next-intl";
import {
  useId,
  useRef,
  useState,
  type ClipboardEvent,
  type DragEvent,
  type KeyboardEvent,
  type ReactNode,
  type Ref
} from "react";
import { CAPABILITIES, readinessKey, type Capability } from "@/features/capabilities/capabilities";
import type { KnowledgeOrigin } from "@/lib/chat/types";
import { cn } from "@/lib/utils";
import { ComposerAttachments } from "./attachments";
import type { ChatCapability } from "./chat-capabilities";
import type { useAttachments } from "./use-attachments";

type Attachments = ReturnType<typeof useAttachments>;

/** Shared look of the composer's pill buttons (attach, capabilities, tools, knowledge). */
const PILL_CLASS =
  "focus-visible:outline-ring inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-[13px] font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:text-ax-text-disabled pointer-coarse:h-11 pointer-coarse:min-w-11";
const PILL_IDLE_CLASS = "text-ax-text-secondary hover:bg-ax-hover hover:text-ax-text";
const PILL_ACTIVE_CLASS = "bg-ax-accent-muted text-ax-text-accent";

/**
 * The composer's text field. A real <textarea> (e2e and assistive tech rely
 * on it) wired to Astryx ChatComposer's context: Enter sends, Shift+Enter adds
 * a line (the hint is in its description), IME composition is respected,
 * pasted files become attachments and Backspace in an empty field removes the
 * last attachment.
 */
function ComposerTextarea({
  label,
  hintId,
  placeholder,
  onEnter,
  onPasteFiles,
  onBackspaceEmpty,
  rows,
  ref
}: {
  label: string;
  hintId: string;
  placeholder: string;
  onEnter: () => void;
  onPasteFiles: (files: File[]) => void;
  onBackspaceEmpty: () => void;
  rows: number;
  ref?: Ref<HTMLTextAreaElement>;
}) {
  const composer = useChatComposerContext();
  const [composing, setComposing] = useState(false);

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      if (composing || event.nativeEvent.isComposing) return;
      event.preventDefault();
      onEnter();
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
      ref={ref}
      name="message"
      rows={rows}
      value={composer?.value ?? ""}
      onChange={(event) => composer?.onChange(event.currentTarget.value)}
      onKeyDown={onKeyDown}
      onPaste={onPaste}
      onCompositionStart={() => setComposing(true)}
      onCompositionEnd={() => setComposing(false)}
      aria-label={label}
      aria-describedby={hintId}
      placeholder={placeholder}
      className="text-ax-text placeholder:text-ax-text-secondary block [field-sizing:content] max-h-48 min-h-[46px] w-full resize-none bg-transparent px-1.5 py-0.5 text-[15px] leading-normal focus:outline-none"
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
            event.preventDefault();
            depth.current = 0;
            setDragging(false);
            const files = Array.from(event.dataTransfer.files ?? []);
            if (files.length > 0) onFiles(files);
          }
        }
      : {}
  };
}

function CapabilityPill({
  capability,
  enabled,
  onToggle
}: {
  capability: ChatCapability;
  enabled: boolean;
  onToggle: () => void;
}) {
  const t = useTranslations();
  const ref = useRef<HTMLButtonElement>(null);
  const descriptor = CAPABILITIES.find((item) => item.purpose === capability.purpose);
  if (!descriptor) return null;
  const Icon: LucideIcon = descriptor.icon;
  const unavailable = !capability.available;
  return (
    <>
      {/* aria-disabled (not disabled) keeps an unavailable capability focusable,
          so its reason (tooltip, also the description) reaches keyboard users. */}
      <button
        ref={ref}
        type="button"
        aria-pressed={enabled}
        aria-disabled={unavailable || undefined}
        onClick={() => {
          if (!unavailable) onToggle();
        }}
        className={cn(
          PILL_CLASS,
          unavailable
            ? "text-ax-text-disabled cursor-not-allowed"
            : enabled
              ? PILL_ACTIVE_CLASS
              : PILL_IDLE_CLASS
        )}
      >
        <Icon aria-hidden="true" className="size-[15px]" />
        <span className="max-sm:sr-only">{t(capability.purpose)}</span>
      </button>
      {unavailable && <Tooltip anchorRef={ref} content={t(readinessKey(capability.reason))} />}
    </>
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
  capabilities: ChatCapability[];
  disabledCapabilities: Set<Capability>;
  onToggleCapability: (purpose: Capability) => void;
  knowledge?: KnowledgeOrigin[];
  /** MCP tools pill (popover with per-server switches). */
  tools?: ReactNode;
  /** Group chats: @-mention picker. */
  mention?: ReactNode;
  /** Personal assistant: model picker on the right. */
  modelSelector?: ReactNode;
  /** Start state for the personal assistant: the assistant selector as a token. */
  partnerToken?: ReactNode;
  /** Context-usage bar, shown under the composer. */
  contextBar?: ReactNode;
  variant?: "docked" | "start";
  textareaRef?: Ref<HTMLTextAreaElement>;
};

/**
 * The chat composer (Astryx ChatComposer): drawer with attachment cards,
 * a textarea, and a row with attach, capability pills (active = accent tint,
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
  capabilities,
  disabledCapabilities,
  onToggleCapability,
  knowledge = [],
  tools,
  mention,
  modelSelector,
  partnerToken,
  contextBar,
  variant = "docked",
  textareaRef
}: ComposerProps) {
  const t = useTranslations();
  const hintId = useId();
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
    <div className="group/composer flex w-full flex-col gap-2">
      <div className="relative" {...handlers}>
        <ChatComposer
          value={value}
          onChange={onChange}
          // Submission runs through `send` (the textarea's Enter and the send
          // button) so a blocked send never clears the field.
          onSubmit={send}
          onStop={onStop}
          isStopShown={busy}
          elevation="none"
          className={cn(
            "rounded-ax-chat [&>div:has(textarea)]:shadow-ax-med",
            variant === "start" && "[&>div:has(textarea)]:rounded-[1.375rem]"
          )}
          drawer={
            hasAttachments ? (
              <ChatComposerDrawer label={t("attachments")}>
                <ComposerAttachments attachments={attachments} />
              </ChatComposerDrawer>
            ) : undefined
          }
          input={
            <ComposerTextarea
              ref={textareaRef}
              label={label}
              hintId={hintId}
              placeholder={placeholder}
              rows={variant === "start" ? 2 : 1}
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
              {capabilities.map((capability) => (
                <CapabilityPill
                  key={capability.purpose}
                  capability={capability}
                  enabled={capability.available && !disabledCapabilities.has(capability.purpose)}
                  onToggle={() => onToggleCapability(capability.purpose)}
                />
              ))}
              {tools}
              {mention}
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
