// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { onlineManager } from "@tanstack/react-query";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { browserApi } from "@/lib/api/browser";
import { recentConversationsQueryOptions } from "@/lib/api/conversations";
import type { ChatPartner, EneoUIMessage } from "@/lib/chat/types";
import { expectNoAxeViolations } from "@/test/axe";
import { composerValue, typeIntoComposer } from "@/test/composer";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import { ChatView, type ActivityState } from "./chat-view";
import type { ToolCallRecord } from "./side-panel/message-tool-calls";

const spies = vi.hoisted(() => ({
  announce: vi.fn(),
  sent: [] as { text: string; body: unknown }[],
  mode: "fail" as
    | "fail"
    | "refused"
    | "json"
    | "answer"
    | "hold"
    | "approval"
    | "approval-break"
    | "provider"
    | "tool",
  titled: [] as string[],
  rated: [] as { path: string; params: unknown; body: unknown }[],
  /** While set, the files upload waits for the test to finish it. */
  holdUpload: null as null | ((upload: { id: string; name: string }) => void)
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
      if (spies.mode === "refused") {
        const { EneoApiError } = await import("@/lib/api/errors");
        throw new EneoApiError("Not authenticated", { status: 401, traceId: "trace-1" });
      }
      // The SDK hands the backend's error text over as an Error message.
      if (spies.mode === "json") throw new Error('{"message":"Not authenticated"}');
      if (spies.mode === "approval" || spies.mode === "approval-break") {
        // A tool asks first; the stream waits for the decision, or breaks.
        return new ReadableStream({
          start(controller) {
            controller.enqueue({ type: "start", messageId: "answer-1" });
            controller.enqueue({
              type: "data-tool-approval",
              id: "ap-1",
              data: {
                approval_id: "ap-1",
                status: "pending",
                tools: [
                  {
                    server_name: "diarium",
                    tool_name: "sok_arende",
                    title: "Sök ärende i diariet",
                    tool_call_id: "call-1",
                    arguments: { arendenummer: "BN 2026-0412" }
                  }
                ]
              }
            });
            if (spies.mode === "approval-break") {
              setTimeout(() => controller.error(new Error("Anslutningen bröts")), 0);
            }
            abortSignal?.addEventListener("abort", () =>
              controller.error(new DOMException("Aborted", "AbortError"))
            );
          }
        });
      }
      if (spies.mode === "provider") {
        const { loadFixtures } = await import("@/lib/chat/contract-fixtures");
        const fixture = loadFixtures().find((item) => item.name === "backend-error")!;
        return new ReadableStream({
          start(controller) {
            for (const chunk of fixture.events) controller.enqueue(chunk);
            controller.close();
          }
        });
      }
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
        ...(spies.mode === "tool"
          ? [
              {
                type: "tool-input-available",
                toolCallId: "call-1",
                toolName: "move_step",
                input: { step_id: "step-2", position: 1 },
                dynamic: true
              },
              {
                type: "tool-output-available",
                toolCallId: "call-1",
                output: { content: [], structuredContent: { draft_revision: 5 } },
                dynamic: true
              }
            ]
          : []),
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
        const uploaded = (upload: { id: string; name: string }) => ({
          data: { ...upload, mimetype: "application/pdf", size: 2048 },
          response: new Response()
        });
        if (spies.holdUpload !== null) {
          return new Promise<ReturnType<typeof uploaded>>((resolve) => {
            spies.holdUpload = (upload) => resolve(uploaded(upload));
          });
        }
        return uploaded({ id: "file-1", name: "Policy.pdf" });
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
vi.mock("@/lib/navigation", () => import("@/test/navigation"));

afterEach(() => {
  cleanup();
  spies.announce.mockReset();
  spies.sent.length = 0;
  spies.titled.length = 0;
  spies.rated.length = 0;
  spies.mode = "fail";
  spies.holdUpload = null;
});

const partner: ChatPartner = {
  type: "assistant",
  id: "assistant-1",
  name: "Upphandlingsassistenten"
};

function Harness({
  onSessionCreated,
  onTitle,
  onToolCallFinished,
  onAnswerFinished,
  chatPartner = partner,
  initialMessages
}: {
  onSessionCreated?: (id: string) => void;
  onTitle?: (title: string) => void;
  onToolCallFinished?: (call: ToolCallRecord) => void;
  onAnswerFinished?: () => void;
  chatPartner?: ChatPartner;
  initialMessages?: EneoUIMessage[];
}) {
  const [activity, setActivity] = useState<ActivityState | null>(null);
  return (
    <ChatView
      partner={chatPartner}
      initialMessages={initialMessages}
      activity={activity}
      onActivityChange={setActivity}
      onSessionCreated={onSessionCreated}
      onTitle={onTitle}
      onToolCallFinished={onToolCallFinished}
      onAnswerFinished={onAnswerFinished}
    />
  );
}

function ask(question: string) {
  const textarea = screen.getByRole("textbox", { name: /^Fråga / });
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

  it("tells the page about each tool call that finished and about the finished answer", async () => {
    spies.mode = "tool";
    const onToolCallFinished = vi.fn();
    const onAnswerFinished = vi.fn();
    renderInApp(
      <Harness onToolCallFinished={onToolCallFinished} onAnswerFinished={onAnswerFinished} />
    );
    ask("Flytta steget först");

    await waitFor(() => expect(onAnswerFinished).toHaveBeenCalledTimes(1));
    expect(onToolCallFinished).toHaveBeenCalledTimes(1);
    expect(onToolCallFinished.mock.calls[0]?.[0]).toMatchObject({
      toolCallId: "call-1",
      toolName: "move_step",
      state: "output-available"
    });
  });

  it("refreshes the partner's history and the recent list once the answer is saved", async () => {
    spies.mode = "answer";
    const queryClient = testQueryClient();
    const history = ["conversations", "assistant", "assistant-1"];
    const recent = recentConversationsQueryOptions(browserApi).queryKey;
    queryClient.setQueryData(history, { pages: [], pageParams: [] });
    queryClient.setQueryData(recent, []);
    renderInApp(<Harness />, { queryClient });
    ask("Vilken gräns gäller?");

    await waitFor(() => expect(queryClient.getQueryState(recent)?.isInvalidated).toBe(true));
    expect(queryClient.getQueryState(history)?.isInvalidated).toBe(true);
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
  // WCAG 2.4.11 and decision 16: the composer sits under the conversation,
  // not over it, so nothing focused can hide behind it; the conversation is
  // the scroller the answer is followed in.
  it("docks the composer under the conversation's scroller, never over it", async () => {
    spies.mode = "answer";
    renderInApp(<Harness />);
    ask("Vilken gräns gäller?");

    const log = await screen.findByRole("log", { name: "Konversation" });
    // useChatStreamScroll marks the element it follows the answer in.
    const scroller = document.querySelector("[data-astryx-chat-following]");
    expect(scroller?.contains(log)).toBe(true);
    const textarea = screen.getByRole("textbox", { name: /^Fråga / });
    expect(scroller?.contains(textarea)).toBe(false);
  });
});

describe("ChatView tool approval on a phone (decision 26)", () => {
  it("puts the decision in the composer's place while the tool waits, then gives it back", async () => {
    spies.mode = "approval";
    setViewport("phone");
    renderInApp(<Harness />);
    ask("Hur långt har ärende BN 2026-0412 kommit?");

    const bar = await screen.findByRole("region", {
      name: /vill använda Sök ärende i diariet$/
    });
    expect(screen.queryByRole("textbox", { name: /^Fråga / })).toBeNull();
    expect(within(bar).getByText("arendenummer: BN 2026-0412")).toBeTruthy();
    // Asked once: the card in the conversation shows the call, the bar decides.
    const card = screen.getByRole("region", { name: "Väntar på godkännande" });
    expect(within(card).queryByRole("button", { name: /^Godkänn/ })).toBeNull();

    fireEvent.click(within(bar).getByRole("button", { name: "Granska Sök ärende i diariet" }));
    const sheet = await screen.findByRole("dialog", { name: "Sök ärende i diariet" });
    expect(within(sheet).getByText("diarium/sok_arende")).toBeTruthy();
    expect(within(sheet).getByRole("button", { name: "Stäng" })).toBeTruthy();

    fireEvent.click(within(bar).getByRole("button", { name: "Godkänn Sök ärende i diariet" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: /^Fråga / })).toBeTruthy());
    expect(
      within(screen.getByRole("region", { name: "Verktygsgodkännande" })).getByText("Godkänt")
    ).toBeTruthy();
  });

  it("keeps the dock for the decision: an earlier answer's sources do not cover it", async () => {
    spies.mode = "approval";
    setViewport("phone");
    const earlier: EneoUIMessage[] = [
      { id: "q0", role: "user", parts: [{ type: "text", text: "Vilken gräns gäller?" }] },
      {
        id: "a0",
        role: "assistant",
        parts: [
          {
            type: "source-document",
            sourceId: "abcd1234-0000",
            mediaType: "text/plain",
            title: "LOU 19 kap."
          },
          { type: "text", text: 'Gränsen är 700 000 kr<inref id="abcd1234"/>.', state: "done" }
        ] as EneoUIMessage["parts"]
      }
    ];
    renderInApp(<Harness initialMessages={earlier} />);
    ask("Hur långt har ärende BN 2026-0412 kommit?");
    await screen.findByRole("region", { name: /vill använda Sök ärende i diariet$/ });

    const source = within(screen.getByRole("list", { name: "Källor" })).getByRole("button", {
      name: "Källa 1: LOU 19 kap."
    });
    fireEvent.click(source);
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Aktivitet för svaret" })).toBeNull()
    );
    // The focus goes back to what opened the sheet, not to the page.
    await waitFor(() => expect(document.activeElement).toBe(source));
    expect(screen.getByRole("region", { name: /vill använda Sök ärende i diariet$/ })).toBeTruthy();
  });

  it("gives the composer back when the stream breaks while a tool waits", async () => {
    spies.mode = "approval-break";
    setViewport("phone");
    renderInApp(<Harness />);
    ask("Hur långt har ärende BN 2026-0412 kommit?");
    expect(await screen.findByRole("button", { name: "Försök igen" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: /vill använda/ })).toBeNull();
    expect(screen.getByRole("textbox", { name: /^Fråga / })).toBeTruthy();
  });
});

describe("ChatView offline", () => {
  afterEach(() => onlineManager.setOnline(true));

  it("keeps the question and says at the field why it cannot be sent", () => {
    spies.mode = "answer";
    renderInApp(<Harness />);
    act(() => void window.dispatchEvent(new Event("offline")));
    const textarea = screen.getByRole("textbox", { name: /^Fråga / }) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "Vilken gräns gäller?" } });
    const sentBefore = spies.sent.length;
    fireEvent.keyDown(textarea, { key: "Enter", ctrlKey: true });

    expect(spies.sent).toHaveLength(sentBefore);
    expect(textarea.value).toBe("Vilken gräns gäller?");
    const description = (textarea.getAttribute("aria-describedby") ?? "")
      .split(" ")
      .map((id) => document.getElementById(id)?.textContent ?? "")
      .join(" ");
    expect(description).toContain("Du är offline. Skicka frågan när du är uppkopplad igen.");
  });
});

describe("ChatView when generation fails", () => {
  it("says the session expired when the request is refused, with status and trace id for support", async () => {
    spies.mode = "refused";
    renderInApp(<Harness />);
    ask("Vilken gräns gäller?");

    expect(await screen.findByText("Din session har gått ut. Logga in igen.")).toBeTruthy();
    expect(spies.announce).toHaveBeenCalledWith("Din session har gått ut. Logga in igen.");
    fireEvent.click(screen.getByRole("button", { name: "Visa detaljer" }));
    const list = await screen.findByRole("list", { name: "Tekniska detaljer" });
    expect(
      within(list)
        .getAllByRole("listitem")
        .map((item) => item.textContent)
    ).toEqual(["HTTP-status 401", "Not authenticated", "Spårnings-ID: trace-1"]);
    await expectNoAxeViolations(document.body);
  });

  it("shows and announces the provider reason, preserves partial text, and clears it on retry", async () => {
    spies.mode = "provider";
    renderInApp(<Harness />);
    ask("Vilken gräns gäller?");
    const message =
      "AI-leverantören har driftstörningar och kunde inte svara. Felet ligger hos leverantören, inte i Eneo. Försök igen om en stund eller välj en annan modell.";
    expect(await screen.findByText(message)).toBeTruthy();
    expect(spies.announce).toHaveBeenCalledWith(message);
    expect(screen.getByText("Partial")).toBeTruthy();
    expect(spies.sent).toHaveLength(1);
    spies.mode = "fail";
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(await screen.findByText("Något gick fel. Försök igen.")).toBeTruthy();
    expect(screen.queryByText(message)).toBeNull();
    expect(spies.announce).toHaveBeenLastCalledWith("Något gick fel. Försök igen.");
    expect(spies.sent).toHaveLength(2);
  });

  it("never shows a JSON error body", async () => {
    spies.mode = "json";
    renderInApp(<Harness />);
    ask("Vilken gräns gäller?");

    expect(await screen.findByText("Något gick fel. Försök igen.")).toBeTruthy();
    expect(document.body.textContent).not.toContain("{");
    fireEvent.click(screen.getByRole("button", { name: "Visa detaljer" }));
    const list = await screen.findByRole("list", { name: "Tekniska detaljer" });
    expect(within(list).getByText("Not authenticated")).toBeTruthy();
    expect(document.body.textContent).not.toContain("{");
  });

  it("shows and announces the error, keeps the question and retries it", async () => {
    renderInApp(<Harness />);
    ask("Vilken gräns gäller?");

    // A sentence, never the raw error; the original text waits behind "Visa detaljer".
    expect(await screen.findByText("Något gick fel. Försök igen.")).toBeTruthy();
    expect(spies.announce).toHaveBeenCalledWith("Något gick fel. Försök igen.");
    const details = screen.getByRole("button", { name: "Visa detaljer" });
    expect(details.getAttribute("aria-expanded")).toBe("false");
    const region = document.getElementById(details.getAttribute("aria-controls") ?? "")!;
    expect(region.contains(screen.getByText("Tjänsten svarar inte"))).toBe(true);
    fireEvent.click(details);
    expect(details.getAttribute("aria-expanded")).toBe("true");
    const list = within(region).getByRole("list", { name: "Tekniska detaljer" });
    expect(within(list).getByText("Tjänsten svarar inte")).toBeTruthy();
    // The failed first question returns to the composer instead of vanishing.
    await waitFor(() =>
      expect((screen.getByRole("textbox", { name: /^Fråga / }) as HTMLTextAreaElement).value).toBe(
        "Vilken gräns gäller?"
      )
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
    const attachments = await screen.findByRole("list", { name: "1 bilaga bifogad" });
    await waitFor(() => expect(within(attachments).queryByText("Laddar upp…")).toBeNull());

    ask("Sammanfatta policyn");
    expect(await screen.findByText("Något gick fel. Försök igen.")).toBeTruthy();
    // Back in the composer (it has the remove button; the log's copy does not).
    await screen.findByRole("button", { name: "Ta bort Policy.pdf" });
    const restored = screen.getByRole("list", { name: "1 bilaga bifogad" });
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

  it("sends a question with uploads still running and issues the request once they are done", async () => {
    vi.stubGlobal(
      "URL",
      Object.assign(URL, { createObjectURL: () => "blob:policy", revokeObjectURL: vi.fn() })
    );
    spies.mode = "answer";
    spies.holdUpload = () => {};
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
    fireEvent.change(input, {
      target: { files: [new File(["%PDF"], "Policy.pdf", { type: "application/pdf" })] }
    });
    await screen.findByRole("list", { name: "1 bilaga bifogad" });

    ask("Sammanfatta policyn");
    // The question is in the conversation at once, with its upload on it,
    // while nothing has been sent and the composer is clear.
    const question = await screen.findByText("Sammanfatta policyn");
    expect(question).toBeTruthy();
    expect(screen.getByText("Laddar upp bilagor (0 av 1)...")).toBeTruthy();
    expect(spies.sent).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "Ta bort Policy.pdf" })).toBeNull();
    expect(screen.getByRole("button", { name: "Stoppa generering" })).toBeTruthy();

    await act(async () => {
      spies.holdUpload!({ id: "file-1", name: "Policy.pdf" });
    });
    await waitFor(() => expect(spies.sent).toHaveLength(1));
    expect(spies.sent[0]?.body).toMatchObject({ files: [{ id: "file-1" }] });
    expect(await screen.findByText("Gränsen är 700 000 kr.")).toBeTruthy();
    expect(screen.queryByText(/Laddar upp bilagor/)).toBeNull();
    vi.unstubAllGlobals();
  });

  it("takes a waiting question back and restores the draft when it is stopped", async () => {
    vi.stubGlobal(
      "URL",
      Object.assign(URL, { createObjectURL: () => "blob:policy", revokeObjectURL: vi.fn() })
    );
    spies.holdUpload = () => {};
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
    fireEvent.change(input, {
      target: { files: [new File(["%PDF"], "Policy.pdf", { type: "application/pdf" })] }
    });
    await screen.findByRole("list", { name: "1 bilaga bifogad" });

    ask("Sammanfatta policyn");
    await screen.findByText("Laddar upp bilagor (0 av 1)...");
    fireEvent.click(screen.getByRole("button", { name: "Stoppa generering" }));

    // Back to the start state with the draft and its attachment in the composer.
    await waitFor(() =>
      expect((screen.getByRole("textbox", { name: /^Fråga / }) as HTMLTextAreaElement).value).toBe(
        "Sammanfatta policyn"
      )
    );
    expect(screen.getByRole("button", { name: "Ta bort Policy.pdf" })).toBeTruthy();
    expect(screen.queryByText(/Laddar upp bilagor/)).toBeNull();
    // The upload finishing later sends nothing by itself.
    await act(async () => {
      spies.holdUpload!({ id: "file-1", name: "Policy.pdf" });
    });
    expect(spies.sent).toHaveLength(0);
    vi.unstubAllGlobals();
  });
});
