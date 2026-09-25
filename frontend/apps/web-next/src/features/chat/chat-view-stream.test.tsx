// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { ChatPartner, EneoUIMessage } from "@/lib/chat/types";
import { ChatView, type ActivityState } from "./chat-view";
import { ChatTestProviders, installDomPolyfills } from "./testing";

const spies = vi.hoisted(() => ({
  announce: vi.fn(),
  sent: [] as { text: string; body: unknown }[],
  mode: "fail" as "fail" | "answer",
  titled: [] as string[]
}));

// Fails before streaming starts, or streams a short answer (AI SDK UI chunks).
vi.mock("@/lib/chat/transport", () => ({
  createChatTransport: () => ({
    sendMessages: async ({ messages, body }: { messages: EneoUIMessage[]; body: unknown }) => {
      const last = messages.at(-1);
      const text = last?.parts.find((part) => part.type === "text");
      spies.sent.push({ text: text?.type === "text" ? text.text : "", body });
      if (spies.mode === "fail") throw new Error("Tjänsten svarar inte");
      const chunks = [
        { type: "start", messageId: "answer-1" },
        {
          type: "data-session",
          data: {
            session_id: "session-1",
            completion_model: { id: "m", name: "claude-haiku", nickname: "Claude Haiku 4.5" },
            files: [],
            web_search_references: []
          }
        },
        { type: "text-start", id: "t" },
        { type: "text-delta", id: "t", delta: "Gränsen är 700 000 kr." },
        { type: "text-end", id: "t" },
        { type: "finish" }
      ];
      return new ReadableStream({
        start(controller) {
          for (const chunk of chunks) controller.enqueue(chunk);
          controller.close();
        }
      });
    },
    reconnectToStream: async () => null
  })
}));
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: vi.fn(async () => ({ data: undefined, response: new Response() })),
    POST: vi.fn(async (path: string, init: { params?: { path?: { session_id?: string } } }) => {
      if (path.endsWith("/title/")) spies.titled.push(init.params?.path?.session_id ?? "");
      return { data: { name: "Gräns för direktupphandling" }, response: new Response() };
    }),
    DELETE: vi.fn(),
    PATCH: vi.fn()
  }
}));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => spies.announce
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

beforeAll(() => installDomPolyfills());
afterEach(() => {
  cleanup();
  spies.announce.mockReset();
  spies.sent.length = 0;
  spies.titled.length = 0;
  spies.mode = "fail";
});

const partner: ChatPartner = {
  type: "assistant",
  id: "assistant-1",
  name: "Upphandlingsassistenten"
};

function Harness({
  onSessionCreated,
  onTitle
}: {
  onSessionCreated?: (id: string) => void;
  onTitle?: (title: string) => void;
}) {
  const [activity, setActivity] = useState<ActivityState | null>(null);
  return (
    <ChatTestProviders>
      <ChatView
        partner={partner}
        activity={activity}
        onActivityChange={setActivity}
        onSessionCreated={onSessionCreated}
        onTitle={onTitle}
      />
    </ChatTestProviders>
  );
}

function ask(question: string) {
  const textarea = screen.getByRole("textbox", { name: /Meddelande till/ });
  fireEvent.change(textarea, { target: { value: question } });
  fireEvent.click(screen.getByRole("button", { name: "Skicka meddelande" }));
}

describe("ChatView streaming an answer", () => {
  it("renders the answer, announces it once, reports the session and asks for a title", async () => {
    spies.mode = "answer";
    const onSessionCreated = vi.fn();
    const onTitle = vi.fn();
    render(<Harness onSessionCreated={onSessionCreated} onTitle={onTitle} />);
    ask("Vilken gräns gäller?");

    const log = await screen.findByRole("log", { name: "Konversation" });
    expect(await within(log).findByText("Gränsen är 700 000 kr.")).toBeTruthy();
    expect(within(log).getByText("Claude Haiku 4.5")).toBeTruthy();
    await waitFor(() => expect(spies.announce).toHaveBeenCalledWith("Svaret är klart"));
    expect(spies.announce).toHaveBeenCalledTimes(1);
    expect(onSessionCreated).toHaveBeenCalledWith("session-1");
    await waitFor(() => expect(onTitle).toHaveBeenCalledWith("Gräns för direktupphandling"));
    expect(spies.titled).toEqual(["session-1"]);
    // A new assistant-first send sends the assistant id, not a session.
    expect(spies.sent[0]?.body).toMatchObject({ assistant_id: "assistant-1", session_id: null });
  });
});

describe("ChatView when generation fails", () => {
  it("shows and announces the error, keeps the question and retries it", async () => {
    render(<Harness />);
    ask("Vilken gräns gäller?");

    expect(await screen.findByText("Tjänsten svarar inte")).toBeTruthy();
    expect(spies.announce).toHaveBeenCalledWith("Tjänsten svarar inte");
    // The failed first question returns to the composer instead of vanishing.
    await waitFor(() =>
      expect(
        (screen.getByRole("textbox", { name: /Meddelande till/ }) as HTMLTextAreaElement).value
      ).toBe("Vilken gräns gäller?")
    );

    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    await waitFor(() => expect(spies.sent).toHaveLength(2));
    expect(spies.sent.map((call) => call.text)).toEqual([
      "Vilken gräns gäller?",
      "Vilken gräns gäller?"
    ]);
  });
});
