// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatPartner, EneoUIMessage } from "@/lib/chat/types";
import { renderInApp, testAppContext } from "@/test/render";
import { observedElements, reportResize } from "@/test/setup-dom";
import { ChatView, type ActivityState } from "./chat-view";

const spies = vi.hoisted(() => ({
  announce: vi.fn(),
  sent: [] as { text: string; body: unknown }[],
  mode: "fail" as "fail" | "answer" | "hold",
  titled: [] as string[],
  rated: [] as { path: string; params: unknown; body: unknown }[]
}));

// Fails before streaming starts, or streams a short answer (AI SDK UI chunks).
vi.mock("@/lib/chat/transport", () => ({
  createChatTransport: () => ({
    sendMessages: async ({
      messages,
      body,
      abortSignal
    }: {
      messages: EneoUIMessage[];
      body: unknown;
      abortSignal?: AbortSignal;
    }) => {
      const last = messages.at(-1);
      const text = last?.parts.find((part) => part.type === "text");
      spies.sent.push({ text: text?.type === "text" ? text.text : "", body });
      if (spies.mode === "fail") throw new Error("Tjänsten svarar inte");
      if (spies.mode === "hold") {
        // Starts answering, then waits until the user stops it.
        return new ReadableStream({
          start(controller) {
            controller.enqueue({ type: "start", messageId: "answer-1" });
            controller.enqueue({ type: "text-start", id: "t" });
            controller.enqueue({ type: "text-delta", id: "t", delta: "Gränsen " });
            abortSignal?.addEventListener("abort", () =>
              controller.error(new DOMException("Aborted", "AbortError"))
            );
          }
        });
      }
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
      if (path === "/api/v1/files/") {
        return {
          data: { id: "file-1", name: "Policy.pdf", mimetype: "application/pdf", size: 2048 },
          response: new Response()
        };
      }
      if (path.endsWith("/title/")) spies.titled.push(init.params?.path?.session_id ?? "");
      return { data: { name: "Gräns för direktupphandling" }, response: new Response() };
    }),
    PUT: vi.fn(async (path: string, init: { params: { path: unknown }; body: unknown }) => {
      spies.rated.push({ path, params: init.params.path, body: init.body });
      return { data: init.body, response: new Response() };
    }),
    DELETE: vi.fn(),
    PATCH: vi.fn()
  }
}));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => spies.announce
}));
vi.mock("next/navigation", () => import("@/test/navigation"));

afterEach(() => {
  cleanup();
  spies.announce.mockReset();
  spies.sent.length = 0;
  spies.titled.length = 0;
  spies.rated.length = 0;
  spies.mode = "fail";
});

const partner: ChatPartner = {
  type: "assistant",
  id: "assistant-1",
  name: "Upphandlingsassistenten"
};

function Harness({
  onSessionCreated,
  onTitle,
  chatPartner = partner
}: {
  onSessionCreated?: (id: string) => void;
  onTitle?: (title: string) => void;
  chatPartner?: ChatPartner;
}) {
  const [activity, setActivity] = useState<ActivityState | null>(null);
  return (
    <ChatView
      partner={chatPartner}
      activity={activity}
      onActivityChange={setActivity}
      onSessionCreated={onSessionCreated}
      onTitle={onTitle}
    />
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
    renderInApp(<Harness onSessionCreated={onSessionCreated} onTitle={onTitle} />);
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

describe("ChatView rating a streamed answer", () => {
  it("offers no rating while the answer streams", async () => {
    spies.mode = "hold";
    renderInApp(<Harness />);
    ask("Vilken gräns gäller?");
    const log = await screen.findByRole("log", { name: "Konversation" });
    await within(log).findByText(/Gränsen/);
    expect(within(log).queryByRole("group", { name: "Betygsätt svaret" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Stoppa generering" }));
    expect(await screen.findByRole("button", { name: "Skicka meddelande" })).toBeTruthy();
  });

  it("rates the finished answer under the id the backend saved it with", async () => {
    spies.mode = "answer";
    renderInApp(<Harness />);
    ask("Vilken gräns gäller?");
    const log = await screen.findByRole("log", { name: "Konversation" });
    const rating = await within(log).findByRole("group", { name: "Betygsätt svaret" });

    fireEvent.click(within(rating).getByRole("button", { name: "Bra svar" }));

    await waitFor(() => expect(spies.rated).toHaveLength(1));
    expect(spies.rated[0]).toEqual({
      path: "/api/v1/conversations/{session_id}/messages/{message_id}/feedback/",
      params: { session_id: "session-1", message_id: "answer-1" },
      body: { value: 1 }
    });
    await waitFor(() => expect(spies.announce).toHaveBeenCalledWith("Tack för din återkoppling"));
  });
});

describe("ChatView sending", () => {
  it("sends an @-mention to the group chat member it names", async () => {
    spies.mode = "answer";
    renderInApp(
      <Harness
        chatPartner={{
          type: "group-chat",
          id: "group-1",
          name: "Upphandlingsgruppen",
          mentionableAssistants: [{ id: "assistant-9", handle: "juristen" }]
        }}
      />
    );
    fireEvent.click(screen.getByRole("combobox", { name: "Nämn" }));
    fireEvent.click(await screen.findByRole("option", { name: "@juristen" }));
    ask("Är avtalet förenligt med LOU?");
    await waitFor(() => expect(spies.sent).toHaveLength(1));
    expect(spies.sent[0]?.body).toMatchObject({
      group_chat_id: "group-1",
      assistant_id: null,
      tools: { assistants: [{ id: "assistant-9", handle: "juristen" }] }
    });
    // The mention applies to that question only.
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "Nämn" }).textContent).toContain("Omnämnanden")
    );
  });

  it("stops an answer from the stop button and says so", async () => {
    spies.mode = "hold";
    renderInApp(<Harness />);
    ask("Vilken gräns gäller?");
    const stop = await screen.findByRole("button", { name: "Stoppa generering" });
    fireEvent.click(stop);
    await waitFor(() => expect(spies.announce).toHaveBeenCalledWith("Svaret stoppades"));
    expect(spies.announce).not.toHaveBeenCalledWith("Svaret är klart");
    expect(await screen.findByRole("button", { name: "Skicka meddelande" })).toBeTruthy();
  });
});

describe("ChatView docked composer", () => {
  // WCAG 2.4.11: the conversation scrolls focused elements above the docked
  // composer. A new conversation mounts the dock only after the first
  // question, and its height must still be tracked.
  it("keeps focus clear of the dock that appears with the first question", async () => {
    spies.mode = "answer";
    renderInApp(<Harness />);
    ask("Vilken gräns gäller?");

    const log = await screen.findByRole("log", { name: "Konversation" });
    const scroller = log.closest<HTMLElement>('[style*="scroll-padding-bottom"]');
    expect(scroller?.style.scrollPaddingBottom).toBe("28px");

    const textarea = screen.getByRole("textbox", { name: /Meddelande till/ });
    const dock = observedElements().find((element) => element.contains(textarea));
    expect(dock).toBeDefined();
    act(() => reportResize(dock!, { height: 150 }));
    expect(scroller?.style.scrollPaddingBottom).toBe("178px");
  });
});

describe("ChatView when generation fails", () => {
  it("shows and announces the error, keeps the question and retries it", async () => {
    renderInApp(<Harness />);
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

  it("puts the question's attachments back in the composer, previews intact", async () => {
    const revoke = vi.fn();
    vi.stubGlobal(
      "URL",
      Object.assign(URL, { createObjectURL: () => "blob:policy", revokeObjectURL: revoke })
    );
    const appContext = testAppContext({
      limits: {
        attachments: {
          formats: [
            { mimetype: "application/pdf", extensions: ["pdf"], size: 10_000_000, vision: false }
          ]
        }
      }
    });
    const { container } = renderInApp(<Harness />, { appContext });
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    const file = new File(["%PDF"], "Policy.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [file] } });
    const attachments = await screen.findByRole("list", { name: "Bilagor" });
    await waitFor(() => expect(within(attachments).getByText(/Klar att använda/)).toBeTruthy());

    ask("Sammanfatta policyn");
    expect(await screen.findByText("Tjänsten svarar inte")).toBeTruthy();
    // Back in the composer (it has the remove button; the log's copy does not).
    await screen.findByRole("button", { name: "Ta bort Policy.pdf" });
    const restored = screen.getByRole("list", { name: "Bilagor" });
    const preview = within(restored).getByRole("button", { name: /^Förhandsvisning: Policy\.pdf/ });
    expect(preview.hasAttribute("disabled")).toBe(false);
    expect(revoke).not.toHaveBeenCalled();
    // A retry that goes through sends the file again, takes it out of the
    // composer and frees its preview.
    spies.mode = "answer";
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    await waitFor(() => expect(spies.sent).toHaveLength(2));
    expect(spies.sent[1]?.body).toMatchObject({ files: [{ id: "file-1" }] });
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Ta bort Policy.pdf" })).toBeNull()
    );
    await waitFor(() => expect(revoke).toHaveBeenCalledWith("blob:policy"));
    vi.unstubAllGlobals();
  });
});
