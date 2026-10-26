// @vitest-environment jsdom
// Finished messages are memoized (chat-view-render.test.tsx counts their
// renders); these check that what they show still follows the conversation.
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import type { ChatPartner, EneoUIMessage } from "@/lib/chat/types";
import { renderInApp } from "@/test/render";
import { ChatView, type ActivityState } from "./chat-view";

type Part = EneoUIMessage["parts"][number];

const probe = vi.hoisted(() => ({
  controller: null as null | ReadableStreamDefaultController
}));

vi.mock("@/lib/chat/transport", () => ({
  createChatTransport: () => ({
    sendMessages: async () =>
      new ReadableStream({
        start(controller) {
          probe.controller = controller;
          controller.enqueue({ type: "start", messageId: "live-1" });
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
vi.mock("next/navigation", () => import("@/test/navigation"));

afterEach(cleanup);

const partner: ChatPartner = { type: "assistant", id: "assistant-1", name: "Assistenten" };

const source = (id: string) =>
  ({
    type: "source-document",
    sourceId: id,
    mediaType: "text/plain",
    title: `Källa ${id}`
  }) as Part;

const history: EneoUIMessage[] = [
  { id: "q0", role: "user", parts: [{ type: "text", text: "Fråga 0?" }] },
  {
    id: "a0",
    role: "assistant",
    parts: [source("s0aaaaaa-1"), { type: "text", text: "Svar 0.", state: "done" }],
    metadata: {
      feedback: null,
      createdAt: "2026-10-01T10:00:00Z",
      generatedFiles: [
        {
          id: "doc-1",
          name: "Plan.md",
          mimetype: "text/markdown",
          size: 10,
          created_at: "2026-10-01T10:00:00Z"
        }
      ]
    } as never
  },
  { id: "q1", role: "user", parts: [{ type: "text", text: "Fråga 1?" }] },
  {
    id: "a1",
    role: "assistant",
    parts: [source("s1bbbbbb-1"), { type: "text", text: "Svar 1.", state: "done" }],
    metadata: { feedback: null, createdAt: "2026-10-01T10:01:00Z" } as never
  }
];

function Harness() {
  const [activity, setActivity] = useState<ActivityState | null>(null);
  return (
    <ChatView
      partner={partner}
      initialMessages={history}
      initialSessionId="session-1"
      activity={activity}
      onActivityChange={setActivity}
    />
  );
}

const settle = () => act(() => new Promise((resolve) => setTimeout(resolve, 80)));
const answers = () =>
  screen.getAllByRole("article").filter((a) => a.textContent?.includes("Assistenten"));
const pillOf = (article: HTMLElement) =>
  within(article).getByRole("button", { name: /aktivitet:/i });

it("saved answers follow the activity pill state", async () => {
  renderInApp(<Harness />);
  const [a0, a1] = answers();
  fireEvent.click(pillOf(a0!));
  await settle();
  expect(pillOf(a0!).getAttribute("aria-expanded")).toBe("true");
  expect(pillOf(a1!).getAttribute("aria-expanded")).toBe("false");
  fireEvent.click(pillOf(a1!));
  await settle();
  expect(pillOf(a0!).getAttribute("aria-expanded")).toBe("false");
  expect(pillOf(a1!).getAttribute("aria-expanded")).toBe("true");
  // The pill toggles closed (the handler sees the current open id).
  fireEvent.click(pillOf(a1!));
  await settle();
  expect(pillOf(a1!).getAttribute("aria-expanded")).toBe("false");
});

it("a saved answer follows the open-file highlight", async () => {
  renderInApp(<Harness />);
  const line = within(answers()[0]!).getByRole("button", { name: /Plan/ });
  expect(line.getAttribute("aria-expanded")).toBe("false");
  fireEvent.click(line);
  await settle();
  expect(
    within(answers()[0]!).getByRole("button", { name: /Plan/ }).getAttribute("aria-expanded")
  ).toBe("true");
});

it("a live answer shows its duration and time once it finishes, and earlier answers see a new version", async () => {
  renderInApp(<Harness />);
  expect(within(answers()[0]!).getByRole("button", { name: /Plan/ }).textContent).not.toContain(
    "Plan v2"
  );
  const field = screen.getByRole("textbox", { name: /Meddelande till/ });
  field.textContent = "Ny fråga";
  fireEvent.input(field);
  fireEvent.click(screen.getByRole("button", { name: "Skicka meddelande" }));
  await settle();
  const c = probe.controller!;
  await act(async () => {
    c.enqueue({
      type: "tool-input-available",
      toolCallId: "call-1",
      toolName: "move_step",
      input: { step_id: "s", position: 1 },
      dynamic: true
    });
  });
  await settle();
  await act(async () => {
    c.enqueue({
      type: "tool-output-available",
      toolCallId: "call-1",
      output: { content: [] },
      dynamic: true
    });
    c.enqueue({ type: "text-start", id: "t" });
    c.enqueue({ type: "text-delta", id: "t", delta: "Klart." });
  });
  await settle();
  const live = answers().at(-1)!;
  expect(live.querySelector("time")).toBeNull();
  await act(async () => {
    c.enqueue({ type: "text-end", id: "t" });
    c.enqueue({
      type: "finish",
      messageMetadata: {
        generatedFiles: [
          {
            id: "doc-2",
            name: "Plan v2.md",
            mimetype: "text/markdown",
            size: 12,
            revises_file_id: "doc-1",
            created_at: "2026-10-02T10:00:00Z"
          }
        ]
      }
    });
    c.close();
  });
  await settle();
  const finished = answers().at(-1)!;
  expect(pillOf(finished).getAttribute("aria-label") ?? pillOf(finished).textContent).toMatch(
    /\d,\d s/
  );
  expect(finished.querySelector("time")).not.toBeNull();
  // The earlier answer's document line now opens (and names) the newest version.
  expect(within(answers()[0]!).getByRole("button", { name: /Plan/ }).textContent).toContain(
    "Plan v2"
  );
});
