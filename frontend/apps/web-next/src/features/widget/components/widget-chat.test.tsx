// @vitest-environment jsdom
import type { WidgetClient, WidgetPublicConfig } from "@eneo/eneo-js";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { flushAnnouncements, renderInApp } from "@/test/render";
import { personaView } from "../persona";
import { WidgetChat } from "./widget-chat";

const PUBLIC_ID = "wgt_aaaaaaaaaaaaaaaaaaaaaa";
const SESSION = "11111111-2222-4333-8444-555555555555";

function config(overrides: Partial<WidgetPublicConfig> = {}): WidgetPublicConfig {
  return {
    public_id: PUBLIC_ID,
    name: "Kaffe",
    texts: {
      title: "Kaffehjälpen",
      subtitle: "AI-assistent om kaffe",
      welcome: "Hej! Fråga mig om kaffe.",
      placeholder: "",
      suggested_questions: ["Hur brygger jag pour over?"],
      footer_text: "",
      footer_link_url: null,
      footer_link_label: null
    },
    theme: { color_scheme: "auto", primary_color: "#1F4E79", radius: 12 },
    persona: null,
    language: "sv",
    bot_protection: "none",
    max_question_chars: 1000,
    token_generation: 1,
    show_sources: true,
    show_tool_activity: true,
    collects_feedback_text: true,
    single_turn: false,
    frame_ancestors: [],
    ...overrides
  } as unknown as WidgetPublicConfig;
}

type Callbacks = NonNullable<Parameters<WidgetClient["conversations"]["ask"]>[0]["callbacks"]>;

type AskArgs = { question: string; callbacks?: Callbacks };

/** The first chunk of an answer: the stored message without its text. */
function firstChunk(question: string, sessionId = SESSION) {
  return {
    id: "m1",
    session_id: sessionId,
    question,
    answer: "",
    files: [],
    generated_files: [],
    references: [],
    tools: { assistants: [] },
    mcp_tool_references: []
  };
}

/** A widget client around the given conversation calls; visitor tokens always mint. */
function clientWith({
  ask,
  leaveFeedback = vi.fn(async () => ({}))
}: {
  ask: ReturnType<typeof vi.fn>;
  leaveFeedback?: ReturnType<typeof vi.fn>;
}) {
  const client = {
    publicId: PUBLIC_ID,
    challenge: vi.fn(),
    config: vi.fn(),
    createVisitorSession: vi.fn(async () => ({
      token: "visitor-token",
      expires_in: 3600,
      visitor_id: "22222222-2222-4333-8444-555555555555",
      visitor_key: "key"
    })),
    conversations: { ask, get: vi.fn(), leaveFeedback }
  };
  return { client: client as unknown as WidgetClient, ask, leaveFeedback };
}

/** A widget client whose answers arrive as one chunk of text. */
function fakeClient(answer = "Pour over: 15 g kaffe på 250 g vatten.") {
  const ask = vi.fn(async ({ question, callbacks }: AskArgs) => {
    const message = firstChunk(question);
    callbacks?.onFirstChunk?.(message as never);
    callbacks?.onText?.({ answer, references: [] } as never);
    return { ...message, answer };
  });
  return clientWith({ ask });
}

/**
 * A widget client whose stream delivers the first chunk and the start of the
 * answer at once, then stays open until the test finishes or fails it.
 */
function streamingClient() {
  const stream: { finish: () => void; fail: (error: unknown) => void } = {
    finish: () => {},
    fail: () => {}
  };
  const ask = vi.fn(({ question, callbacks }: AskArgs) => {
    const message = firstChunk(question);
    callbacks?.onFirstChunk?.(message as never);
    callbacks?.onText?.({ answer: "Pour over:", references: [] } as never);
    return new Promise<typeof message>((resolve, reject) => {
      stream.finish = () => resolve({ ...message, answer: "Pour over: 15 g kaffe." });
      stream.fail = reject;
    });
  });
  return { ...clientWith({ ask }), stream };
}

/** The conversation the visitor's storage would restore; undefined before a token was minted. */
function rememberedSession(): string | null | undefined {
  const raw = localStorage.getItem(`eneo-widget:${PUBLIC_ID}`);
  return raw ? (JSON.parse(raw) as { session_id: string | null }).session_id : undefined;
}

function typeQuestion(question: string) {
  const field = screen.getByRole("textbox", { name: "Din fråga" });
  fireEvent.change(field, { target: { value: question } });
  fireEvent.keyDown(field, { key: "Enter" });
}

/** The header's new-conversation button, confirmed. */
async function startOver() {
  fireEvent.click(screen.getByRole("button", { name: "Ny konversation" }));
  const dialog = await screen.findByRole("alertdialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Starta ny" }));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
}

/** Alerts with something in them; Astryx's assertive live region is one while empty. */
function shownAlerts(): string[] {
  return screen
    .queryAllByRole("alert")
    .map((alert) => alert.textContent?.trim() ?? "")
    .filter(Boolean);
}

function renderChat(widget: WidgetPublicConfig, client: WidgetClient) {
  return renderInApp(
    <WidgetChat
      config={widget}
      client={client}
      hostOrigin={null}
      onSession={() => {}}
      persona={personaView(widget)}
    />
  );
}

/** What Astryx's live regions hold right now. */
function announced(): string {
  return Array.from(document.querySelectorAll("[aria-live]"))
    .map((region) => region.textContent?.trim() ?? "")
    .filter(Boolean)
    .join(" | ");
}

afterEach(() => localStorage.clear());

describe("WidgetChat", () => {
  it("opens with the welcome text and sends the first question", async () => {
    const { client, ask } = fakeClient();
    renderChat(config(), client);

    expect(screen.getByRole("heading", { level: 1, name: "Kaffehjälpen" })).toBeTruthy();
    expect(screen.getByRole("banner", { name: "Kaffehjälpen" })).toBeTruthy();
    expect(
      within(screen.getByRole("main", { name: "Kaffehjälpen" })).getByText(
        "Hej! Fråga mig om kaffe."
      )
    ).toBeTruthy();
    // Without a persona the welcome text is a plain paragraph, outside the log.
    expect(screen.queryByRole("log")).toBeNull();

    fireEvent.change(screen.getByRole("textbox", { name: "Din fråga" }), {
      target: { value: "Hur brygger jag?" }
    });
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Din fråga" }), { key: "Enter" });

    const log = await screen.findByRole("log", { name: "Konversation" });
    await within(log).findByText("Pour over: 15 g kaffe på 250 g vatten.");
    expect(within(log).getByText("Hur brygger jag?")).toBeTruthy();
    expect(ask).toHaveBeenCalledExactlyOnceWith(
      expect.objectContaining({ question: "Hur brygger jag?", conversation: { id: null } })
    );
    // The finished answer is read once, prefixed by who answered.
    await waitFor(() =>
      expect(announced()).toContain("Assistent: Pour over: 15 g kaffe på 250 g vatten.")
    );
    // The composer keeps the keyboard for the next question.
    expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "Din fråga" }));
  });

  it("with a persona, opens with its first message and names every answer", async () => {
    const { client } = fakeClient();
    renderChat(
      config({
        persona: { name: "Sigge", avatar_icon_id: null, avatar_in_launcher: false }
      } as Partial<WidgetPublicConfig>),
      client
    );

    // The welcome text is the persona's first message, inside the log.
    const log = screen.getByRole("log", { name: "Konversation" });
    expect(within(log).getByText("Hej! Fråga mig om kaffe.")).toBeTruthy();
    expect(within(log).getAllByText("Sigge")).toHaveLength(1);
    expect(within(log).getByText("AI-assistent", { selector: ".sr-only" })).toBeTruthy();
    // The monogram stands in for a missing avatar.
    expect(within(log).getByText("S")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Hur brygger jag pour over?" }));
    await within(log).findByText("Pour over: 15 g kaffe på 250 g vatten.");
    // One byline per message: the opening and the answer.
    expect(within(log).getAllByText("Sigge")).toHaveLength(2);
    await waitFor(() => expect(announced()).toContain("Sigge: Pour over"));
  });

  it("takes a vote on the conversation and acknowledges it", async () => {
    const { client, leaveFeedback } = fakeClient();
    renderChat(config(), client);
    fireEvent.click(screen.getByRole("button", { name: "Hur brygger jag pour over?" }));
    await screen.findByText("Pour over: 15 g kaffe på 250 g vatten.");

    // The thumbs open once the answer has fully arrived.
    const helpful = await screen.findByRole("button", { name: "Hjälpsam konversation" });
    await waitFor(() => expect((helpful as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(helpful);
    await waitFor(() =>
      expect(leaveFeedback).toHaveBeenCalledExactlyOnceWith({
        conversation: { id: SESSION },
        feedback: { value: 1 }
      })
    );
    await screen.findByText("Tack för din återkoppling på konversationen");
    expect(screen.getByRole("button", { name: "Ändra omdöme" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Hjälpsam konversation" })).toBeNull();
  });

  it("keeps sending unavailable while a remembered conversation renews its token", async () => {
    const { client, ask } = fakeClient();
    const visitor = "22222222-2222-4333-8444-555555555555";
    localStorage.setItem(
      `eneo-widget:${PUBLIC_ID}`,
      JSON.stringify({
        visitor_id: visitor,
        visitor_key: "key",
        token: "expired",
        expires_at: Date.now() - 1000,
        session_id: SESSION
      })
    );
    let finishRenewal!: (value: unknown) => void;
    vi.mocked(client.createVisitorSession).mockImplementationOnce(
      () => new Promise((resolve) => (finishRenewal = resolve)) as never
    );
    vi.mocked(client.conversations.get).mockResolvedValue({
      id: SESSION,
      messages: [{ ...firstChunk("Tidigare fråga"), answer: "Tidigare svar" }],
      feedback: null
    } as never);
    renderChat(config(), client);
    await waitFor(() => expect(client.createVisitorSession).toHaveBeenCalledTimes(1));

    // Renewal still pending: a question must not start a conversation of its own.
    typeQuestion("Under förnyelsen");
    await act(async () => {});
    expect(ask).not.toHaveBeenCalled();
    // The draft stays in the box; nothing of it is shown as sent.
    expect(screen.queryByRole("log")).toBeNull();

    await act(async () =>
      finishRenewal({ token: "renewed", expires_in: 3600, visitor_id: visitor, visitor_key: "key" })
    );
    await screen.findByText("Tidigare svar");
    typeQuestion("Efter förnyelsen");
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(1));
    expect(ask).toHaveBeenLastCalledWith(
      expect.objectContaining({ question: "Efter förnyelsen", conversation: { id: SESSION } })
    );
    await screen.findByText("Pour over: 15 g kaffe på 250 g vatten.");
    expect(rememberedSession()).toBe(SESSION);
  });

  it("discards a follow-up while its token is being renewed", async () => {
    const { client, ask } = fakeClient();
    const token = { token: "first", expires_in: 1, visitor_id: SESSION, visitor_key: "key" };
    let finishRenewal!: (value: typeof token) => void;
    vi.mocked(client.createVisitorSession)
      .mockResolvedValueOnce(token)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finishRenewal = resolve;
          })
      );
    renderChat(config(), client);
    typeQuestion("Första frågan");
    await screen.findByText("Pour over: 15 g kaffe på 250 g vatten.");
    typeQuestion("Kasta den här");
    await waitFor(() => expect(client.createVisitorSession).toHaveBeenCalledTimes(2));
    await startOver();
    await act(async () => finishRenewal({ ...token, token: "renewed", expires_in: 3600 }));
    expect(ask).toHaveBeenCalledTimes(1);
    expect(rememberedSession()).toBeNull();
    typeQuestion("Ny fråga");
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask).toHaveBeenLastCalledWith(
      expect.objectContaining({ question: "Ny fråga", conversation: { id: null } })
    );
  });

  it.each([
    ["finishes", (stream: { finish: () => void }) => stream.finish()],
    ["fails", (stream: { fail: (error: unknown) => void }) => stream.fail(new Error("aborted"))]
  ])(
    "keeps nothing of a conversation started over while its answer streamed, once the stream %s",
    async (_outcome, settle) => {
      const { client, ask, stream } = streamingClient();
      renderChat(config(), client);
      typeQuestion("Hur brygger jag?");
      const log = await screen.findByRole("log", { name: "Konversation" });
      await within(log).findByText("Pour over:");
      // The visitor has an identity, and no conversation is kept until the answer ends.
      expect(rememberedSession()).toBeNull();

      await startOver();
      expect(screen.queryByRole("log")).toBeNull();
      await act(async () => settle(stream));
      await flushAnnouncements();

      // The old send is over: the pending question goes with it.
      await waitFor(() => expect(screen.queryByRole("log")).toBeNull());
      expect(rememberedSession()).toBeNull();
      expect(shownAlerts()).toEqual([]);
      expect(announced()).not.toContain("Pour over");
      expect(announced()).not.toContain("Svaret är klart");
      // The next question starts a conversation of its own.
      typeQuestion("Och espresso?");
      await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
      expect(ask).toHaveBeenLastCalledWith(
        expect.objectContaining({ question: "Och espresso?", conversation: { id: null } })
      );
    }
  );

  it("retries a vote on the conversation it was given for, not the one started since", async () => {
    const SESSION_B = "66666666-7777-4888-8999-000000000000";
    const sessions = [SESSION, SESSION_B];
    const ask = vi.fn(async ({ question, callbacks }: AskArgs) => {
      const message = firstChunk(question, sessions.shift());
      callbacks?.onFirstChunk?.(message as never);
      callbacks?.onText?.({ answer: "Svar.", references: [] } as never);
      return { ...message, answer: "Svar." };
    });
    let rejectFirst!: (error: unknown) => void;
    const leaveFeedback = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise((_resolve, reject) => {
            rejectFirst = reject;
          })
      )
      .mockResolvedValue({});
    const { client } = clientWith({ ask, leaveFeedback });
    renderChat(config(), client);

    fireEvent.click(screen.getByRole("button", { name: "Hur brygger jag pour over?" }));
    await screen.findByText("Svar.");
    const helpful = await screen.findByRole("button", { name: "Hjälpsam konversation" });
    await waitFor(() => expect((helpful as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(helpful);
    await waitFor(() => expect(leaveFeedback).toHaveBeenCalledTimes(1));

    // The vote is still on its way when the visitor starts over and asks again.
    await startOver();
    typeQuestion("Och nu?");
    await screen.findByText("Svar.");
    await screen.findByRole("button", { name: "Hjälpsam konversation" });
    expect(ask).toHaveBeenLastCalledWith(expect.objectContaining({ conversation: { id: null } }));

    const { EneoError } = await import("@eneo/eneo-js");
    await act(async () =>
      rejectFirst(
        new EneoError(
          "expired",
          "SERVER",
          401,
          0,
          { detail: { code: "token_expired" } },
          { endpoint: "/feedback" }
        )
      )
    );
    await waitFor(() => expect(leaveFeedback).toHaveBeenCalledTimes(2));
    expect(leaveFeedback).toHaveBeenNthCalledWith(2, {
      conversation: { id: SESSION },
      feedback: { value: 1 }
    });
    expect(
      leaveFeedback.mock.calls.some(
        (call) => (call[0] as { conversation: { id: string } }).conversation.id === SESSION_B
      )
    ).toBe(false);
    await flushAnnouncements();
    // The new conversation is untouched: its thumbs are still open and nothing was acknowledged.
    const thumb = screen.getByRole("button", { name: "Hjälpsam konversation" });
    expect(thumb.getAttribute("aria-pressed")).toBe("false");
    expect(screen.queryByText("Tack för din återkoppling på konversationen")).toBeNull();
    expect(announced()).not.toContain("Tack för din återkoppling");
    expect(shownAlerts()).toEqual([]);
  });

  it("puts a refused question back in the field and says what happened", async () => {
    const { client, ask } = fakeClient();
    const { EneoError } = await import("@eneo/eneo-js");
    ask.mockRejectedValueOnce(
      new EneoError(
        "busy",
        "SERVER",
        429,
        0,
        { detail: { code: "rate_limited_ip" } },
        {
          endpoint: "/ask"
        }
      )
    );
    renderChat(config(), client);
    const field = screen.getByRole("textbox", { name: "Din fråga" });
    fireEvent.change(field, { target: { value: "Hej?" } });
    fireEvent.keyDown(field, { key: "Enter" });

    await screen.findByRole("alert");
    expect((field as HTMLTextAreaElement).value).toBe("Hej?");
    expect(screen.queryByRole("log")).toBeNull();
  });

  it("passes the WCAG 2.2 A/AA rules with a persona, an answer and the sources closed", async () => {
    const { client } = fakeClient();
    const { container } = renderChat(
      config({
        persona: { name: "Sigge", avatar_icon_id: null, avatar_in_launcher: false }
      } as Partial<WidgetPublicConfig>),
      client
    );
    fireEvent.click(screen.getByRole("button", { name: "Hur brygger jag pour over?" }));
    await screen.findByText("Pour over: 15 g kaffe på 250 g vatten.");
    await act(async () => {
      await expectNoAxeViolations(container);
    });
  });
});
