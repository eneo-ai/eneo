"use client";

import {
  ChatLayoutScrollButton,
  useChatNewMessages,
  useChatStreamScroll
} from "@astryxdesign/core/Chat";
import { useTranslator } from "@astryxdesign/core/i18n";
import { useRef, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * A started conversation: the messages scroll, the composer sits flat under
 * them (decision 16: no glass) and never covers one, so nothing focused can
 * hide behind it (WCAG 2.4.11) at any width.
 *
 * Astryx ChatLayout's wiring, kept: the answer is followed while the reader
 * is at the bottom (`useChatStreamScroll`; its overflow-anchor rule comes
 * nonce'd from the root layout under the CSP), and a button scrolls to the
 * latest, "Nya meddelanden" when an answer grew out of view
 * (`useChatNewMessages` watches the content wrapper, as ChatLayout's context
 * is not exported). It mounts with the scroller: the hooks attach to it once.
 */
export function ConversationLayout({
  children,
  composer,
  className
}: {
  /** The message list. */
  children: ReactNode;
  /** The docked composer. */
  composer: ReactNode;
  className?: string;
}) {
  const t = useTranslator();
  const scrollRef = useRef<HTMLDivElement>(null);
  const { isScrolledUp, isLocked, scrollIfLocked, scrollToBottom } = useChatStreamScroll({
    scrollRef
  });
  const { contentRef, hasNewMessages, dismiss } = useChatNewMessages({
    isLocked,
    onResize: scrollIfLocked
  });

  return (
    <div className={cn("flex min-h-0 flex-col", className)}>
      {/* overflow-hidden: the scroll button slides out of view when hidden,
          and must not make the page panel scroll with it. */}
      <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
        <div
          ref={scrollRef}
          // The list pads itself 16 px; the dock's 16 px lines the composer up with it.
          className="flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-y-contain pb-6"
        >
          <div ref={contentRef} className="flex flex-1 flex-col">
            {children}
          </div>
        </div>
        <div className="pointer-events-none absolute inset-x-0 bottom-0">
          <ChatLayoutScrollButton
            isVisible={isScrolledUp || hasNewMessages}
            label={hasNewMessages ? t("@astryx.chatLayout.newMessages") : undefined}
            onClick={() => {
              dismiss();
              scrollToBottom();
            }}
          />
        </div>
      </div>
      <div className="shrink-0 px-4 pt-1 pb-3">{composer}</div>
    </div>
  );
}
