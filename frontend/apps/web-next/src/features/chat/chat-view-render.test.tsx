// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import type { ChatPartner, EneoUIMessage } from "@/lib/chat/types";
import { chatComposer, typeIntoComposer } from "@/test/composer";
import { renderInApp } from "@/test/render";
import { ChatView, type ActivityState } from "./chat-view";

// Counts how often each message renders.
const probe = vi.hoisted(() => ({
  renders: new Map<string, number>(),
  controller: null as null | ReadableStreamDefaultController
}));

vi.mock("./chat-message", async (importOriginal) => {
  const original = await importOriginal<typeof import("./chat-message")>();
  return {
    ...original,
    ChatMessage: (props: React.ComponentProps<typeof original.ChatMessage>) => {
      probe.renders.set(props.message.id, (probe.renders.get(props.message.id) ?? 0) + 1);
      return original.ChatMessage(props) as never;
    }
  };
});
vi.mock("@/lib/chat/transport", () => ({
  createChatTransport: () => ({
    sendMessages: async () =>
      new ReadableStream({
        start(controller) {
          probe.controller = controller;
          controller.enqueue({ type: "start", messageId: "live-1" });
          controller.enqueue({ type: "text-start", id: "t" });
        }
      }),
    reconnectToStream: async () => null
  })
}));
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: vi.fn(async () => ({ data: undefined, response: new Response() })),
    POST: vi.fn(async () => ({ data: { name: "t" }, response: new Response() })),
    PUT: vi.fn(),
    DELETE: vi.fn(),
    PATCH: vi.fn()
  }
}));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));

afterEach(cleanup);

const partner: ChatPartner = { type: "assistant", id: "assistant-1", name: "Assistenten" };

function history(pairs: number): EneoUIMessage[] {
  return Array.from({ length: pairs }, (_, i): EneoUIMessage[] => [
    { id: `h${i}-q`, role: "user", parts: [{ type: "text", text: `Fråga ${i}?` }] },
    {
      id: `h${i}`,
      role: "assistant",
      parts: [{ type: "text", text: `Svar ${i} med **fet** text.`, state: "done" }],
      metadata: { feedback: null, createdAt: "2026-10-01T10:00:00Z" } as never
    }
  ]).flat();
}

function Harness() {
  const [activity, setActivity] = useState<ActivityState | null>(null);
  return (
    <ChatView
      partner={partner}
      initialMessages={history(10)}
      initialSessionId="session-1"
      activity={activity}
      onActivityChange={setActivity}
    />
  );
}

const savedRenders = () =>
  [...probe.renders].filter(([id]) => id.startsWith("h")).reduce((sum, [, n]) => sum + n, 0);

const settle = () => act(() => new Promise((resolve) => setTimeout(resolve, 80)));

it("renders a finished message again only when what it shows changes", async () => {
  renderInApp(<Harness />);
  expect(savedRenders()).toBeGreaterThan(0);

  // Typing in the composer.
  probe.renders.clear();
  const field = chatComposer();
  for (const text of ["h", "he", "hej"]) typeIntoComposer(field, text);
  expect(savedRenders()).toBe(0);

  // Streaming an answer.
  fireEvent.click(screen.getByRole("button", { name: "Skicka meddelande" }));
  await settle();
  expect(probe.controller).not.toBeNull();
  probe.renders.clear();
  for (let i = 0; i < 5; i++) {
    await act(async () =>
      probe.controller!.enqueue({ type: "text-delta", id: "t", delta: `ord${i} ` })
    );
    await settle();
  }
  expect(savedRenders()).toBe(0);
  expect(probe.renders.get("live-1") ?? 0).toBeGreaterThan(0);

  // The answer finished in this visit is not rendered again by typing either.
  await act(async () => {
    probe.controller!.enqueue({ type: "text-end", id: "t" });
    probe.controller!.enqueue({ type: "finish" });
    probe.controller!.close();
  });
  await settle();
  probe.renders.clear();
  for (const text of ["o", "oc", "och"]) typeIntoComposer(chatComposer(), text);
  expect(probe.renders.get("live-1") ?? 0).toBe(0);
  expect(savedRenders()).toBe(0);
});
