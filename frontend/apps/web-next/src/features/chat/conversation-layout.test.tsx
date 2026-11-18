// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const scroll = vi.hoisted(() => ({
  scrollToBottom: vi.fn(),
  dismiss: vi.fn()
}));
vi.mock("@astryxdesign/core/Chat", () => ({
  ChatLayoutScrollButton: () => null,
  useChatStreamScroll: () => ({
    isScrolledUp: true,
    isLocked: false,
    scrollIfLocked: () => {},
    scrollToBottom: scroll.scrollToBottom
  }),
  useChatNewMessages: () => ({
    contentRef: { current: null },
    hasNewMessages: true,
    dismiss: scroll.dismiss
  })
}));
vi.mock("@astryxdesign/core/i18n", () => ({ useTranslator: () => (key: string) => key }));

import { ConversationLayout } from "./conversation-layout";

beforeEach(() => vi.clearAllMocks());

const layout = (followKey: string, children = "meddelanden") => (
  <ConversationLayout composer={<div />} followKey={followKey}>
    {children}
  </ConversationLayout>
);

it("jumps to the end when a question is sent, not when an answer grows, and not on first paint", () => {
  const view = render(layout("1:"));
  expect(scroll.scrollToBottom).not.toHaveBeenCalled();

  // An answer growing under a reader who scrolled up must not pull them down.
  view.rerender(layout("1:", "ett längre svar"));
  expect(scroll.scrollToBottom).not.toHaveBeenCalled();

  // A new question: the list shows it and its answer, whatever was scrolled to.
  view.rerender(layout("2:"));
  expect(scroll.scrollToBottom).toHaveBeenCalledTimes(1);
  expect(scroll.scrollToBottom).toHaveBeenCalledWith({ behavior: "instant" });
  expect(scroll.dismiss).toHaveBeenCalledTimes(1);

  // The question's own pending state: once.
  view.rerender(layout("2:pending"));
  expect(scroll.scrollToBottom).toHaveBeenCalledTimes(2);
});
