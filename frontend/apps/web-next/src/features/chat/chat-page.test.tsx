// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { ChatPartner } from "@/lib/chat/types";
import { expectNoAxeViolations } from "@/test/axe";
import { ChatPage } from "./chat-page";
import { ChatTestProviders, installDomPolyfills } from "./testing";

type Chunk = Record<string, unknown>;

function deferred<T = void>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const spies = vi.hoisted(() => ({
  announce: vi.fn(),
  toastError: vi.fn(),
  /** One controller per sent question, to stream its answer from the test. */
  streams: [] as ReadableStreamDefaultController<Chunk>[],
  /** When set, the next question fails once this settles (before any answer). */
  failAfter: null as Promise<void> | null,
  titled: [] as string[],
  detailCalls: [] as string[],
  signals: new Map<string, AbortSignal | undefined>(),
  /** Detail responses the test holds back, by session id. */
  heldDetails: new Map<string, Promise<void>>()
}));

vi.mock("@/lib/chat/transport", () => ({
  createChatTransport: () => ({
    sendMessages: async () => {
      if (spies.failAfter) {
        const gate = spies.failAfter;
        spies.failAfter = null;
        await gate;
        throw new Error("Tjänsten svarar inte");
      }
      return new ReadableStream<Chunk>({
        start(controller) {
          spies.streams.push(controller);
          controller.enqueue({ type: "start", messageId: `answer-${spies.streams.length}` });
        }
      });
    },
    reconnectToStream: async () => null
  })
}));

const api = vi.hoisted(() => ({
  GET: vi.fn(
    async (
      path: string,
      init?: { params?: { path?: { session_id?: string } }; signal?: AbortSignal }
    ) => {
      if (path === "/api/v1/conversations/{session_id}/") {
        const id = init?.params?.path?.session_id ?? "";
        spies.detailCalls.push(id);
        spies.signals.set(id, init?.signal);
        await spies.heldDetails.get(id);
        if (id === "s-missing") {
          return {
            data: undefined,
            error: { message: "Not found" },
            response: new Response(null, { status: 404 })
          };
        }
        return {
          data: {
            id,
            name: id === "s-untitled" ? "" : `Samtal ${id}`,
            feedback: null,
            messages: [
              {
                id: `m-${id}`,
                question: `Fråga i ${id}`,
                answer: `Svar i ${id}`,
                references: [],
                files: [],
                generated_files: [],
                tools: { assistants: [] }
              }
            ]
          },
          response: new Response()
        };
      }
      if (path === "/api/v1/conversations/") {
        return {
          data: {
            items: [{ id: "s-1", name: "Samtal s-1", updated_at: new Date().toISOString() }],
            total_count: 1,
            next_cursor: null
          },
          response: new Response()
        };
      }
      if (path === "/api/v1/analysis/conversation-insights/") {
        return {
          data: { total_conversations: 12, total_questions: 30 },
          response: new Response()
        };
      }
      return { data: { items: [], next_cursor: null }, response: new Response() };
    }
  ),
  POST: vi.fn(async (path: string, init?: { params?: { path?: { session_id?: string } } }) => {
    if (path.endsWith("/title/")) {
      spies.titled.push(init?.params?.path?.session_id ?? "");
      return { data: { name: "Gräns för direktupphandling" }, response: new Response() };
    }
    return { data: {}, response: new Response() };
  }),
  PATCH: vi.fn(),
  DELETE: vi.fn(async () => ({ data: null, response: new Response(null, { status: 204 }) }))
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => spies.announce
}));
vi.mock("sonner", async (importOriginal) => {
  const original = await importOriginal<typeof import("sonner")>();
  return {
    ...original,
    toast: Object.assign(vi.fn(), { ...original.toast, error: spies.toastError })
  };
});

beforeAll(() => installDomPolyfills());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  spies.announce.mockReset();
  spies.toastError.mockReset();
  spies.streams.length = 0;
  spies.failAfter = null;
  spies.titled.length = 0;
  spies.detailCalls.length = 0;
  spies.signals.clear();
  spies.heldDetails.clear();
});

const partner: ChatPartner = {
  type: "assistant",
  id: "assistant-1",
  name: "Upphandlingsassistenten",
  spaceName: "Upphandling"
};

const buildSessionUrl = (id: string | null) => (id ? `/chat?session_id=${id}` : "/chat");

function renderPage(sessionId: string | null, pagePartner: ChatPartner = partner) {
  const view = render(
    <ChatTestProviders>
      <ChatPage partner={pagePartner} sessionId={sessionId} buildSessionUrl={buildSessionUrl} />
    </ChatTestProviders>
  );
  const rerender = (next: string | null) =>
    view.rerender(
      <ChatTestProviders>
        <ChatPage partner={pagePartner} sessionId={next} buildSessionUrl={buildSessionUrl} />
      </ChatTestProviders>
    );
  return rerender;
}

function composer() {
  return screen.getByRole("textbox", { name: /Meddelande till/ }) as HTMLTextAreaElement;
}

/** Types a question and presses Enter in the composer, as a keyboard user does. */
function askWithKeyboard(question: string) {
  const textarea = composer();
  textarea.focus();
  fireEvent.change(textarea, { target: { value: question } });
  fireEvent.keyDown(textarea, { key: "Enter" });
}

/** Streams a complete answer for a question that is waiting for one. */
function answer(stream: ReadableStreamDefaultController<Chunk>, sessionId: string, text: string) {
  const chunks: Chunk[] = [
    {
      type: "data-session",
      data: { session_id: sessionId, files: [], web_search_references: [] }
    },
    { type: "text-start", id: "t" },
    { type: "text-delta", id: "t", delta: text },
    { type: "text-end", id: "t" },
    { type: "finish" }
  ];
  for (const chunk of chunks) stream.enqueue(chunk);
  stream.close();
}

function h1Texts() {
  return screen.getAllByRole("heading", { level: 1 }).map((heading) => heading.textContent);
}

describe("ChatPage", () => {
  it("follows ?session_id= on the same route and starts fresh without one", async () => {
    const rerender = renderPage(null);
    expect(screen.getByRole("heading", { level: 1, name: "Upphandlingsassistenten" })).toBeTruthy();

    rerender("s-1");
    const log = await screen.findByRole("log", { name: "Konversation" });
    expect(within(log).getByText("Svar i s-1")).toBeTruthy();
    expect(screen.getAllByRole("heading", { level: 1, name: "Samtal s-1" }).length).toBeGreaterThan(
      0
    );

    rerender("s-2");
    await waitFor(() =>
      expect(within(screen.getByRole("log")).getByText("Svar i s-2")).toBeTruthy()
    );

    // "Ny konversation" in the SideNav: the same route without session_id.
    rerender(null);
    await waitFor(() => expect(screen.queryByRole("log")).toBeNull());
    expect(screen.getByRole("heading", { level: 1, name: "Upphandlingsassistenten" })).toBeTruthy();
    expect(spies.detailCalls).toEqual(["s-1", "s-2"]);
  });

  it("does not reload the conversation it already shows", async () => {
    const rerender = renderPage("s-1");
    await screen.findByRole("log", { name: "Konversation" });
    rerender("s-1");
    await waitFor(() => expect(screen.getByRole("log")).toBeTruthy());
    expect(spies.detailCalls).toEqual(["s-1"]);
  });

  it("shows the conversation picked last when an earlier pick answers late", async () => {
    const slow = deferred();
    spies.heldDetails.set("s-slow", slow.promise);
    const rerender = renderPage("s-slow");
    rerender("s-2");
    const log = await screen.findByRole("log", { name: "Konversation" });
    expect(within(log).getByText("Svar i s-2")).toBeTruthy();
    // The earlier request is cancelled.
    expect(spies.signals.get("s-slow")?.aborted).toBe(true);

    await act(async () => slow.resolve());
    expect(within(screen.getByRole("log")).getByText("Svar i s-2")).toBeTruthy();
    expect(screen.queryByText("Svar i s-slow")).toBeNull();
  });

  it("says once, next to the conversation, that it could not be loaded", async () => {
    renderPage("s-missing");
    const message = await screen.findByText("Konversationen kunde inte laddas.");
    expect(spies.toastError).not.toHaveBeenCalled();
    expect(
      within(message.parentElement!).getByRole("button", { name: "Ny konversation" })
    ).toBeTruthy();
  });

  it("titles an untitled conversation instead of rendering an empty heading", async () => {
    renderPage("s-untitled");
    await screen.findByRole("log", { name: "Konversation" });
    expect(h1Texts()).toEqual(["Ny konversation", "Ny konversation"]);
  });

  it("updates the open answer's thumbs when the history rates its conversation", async () => {
    renderPage("s-1");
    const log = await screen.findByRole("log", { name: "Konversation" });
    const good = within(log).getByRole("button", { name: "Bra svar" });
    expect(good.getAttribute("aria-pressed")).toBe("false");

    fireEvent.click(screen.getByRole("button", { name: "Historik" }));
    const trigger = await screen.findByRole("button", { name: "Åtgärder för Samtal s-1" });
    fireEvent.click(trigger);
    const menu = document.getElementById(trigger.getAttribute("aria-controls") ?? "")!;
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Betygsätt som bra" }));
    await waitFor(() => expect(good.getAttribute("aria-pressed")).toBe("true"));
  });

  it("starts over with focus in the composer after deleting the open conversation", async () => {
    renderPage("s-1");
    await screen.findByRole("log", { name: "Konversation" });
    const [more] = screen.getAllByRole("button", { name: "Fler alternativ" });
    fireEvent.click(more!);
    const menu = document.getElementById(more!.getAttribute("aria-controls") ?? "")!;
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Ta bort konversationen" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Ta bort konversationen" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Bekräfta borttagning" }));

    await waitFor(() => expect(screen.queryByRole("log")).toBeNull());
    expect(api.DELETE).toHaveBeenCalled();
    await waitFor(() => expect(document.activeElement).toBe(composer()));
  });

  it("has no axe violations with a loaded conversation", async () => {
    renderPage("s-1");
    await screen.findByRole("log", { name: "Konversation" });
    await expectNoAxeViolations(document.body);
  });
});

describe("ChatPage while an answer streams", () => {
  it("keeps an answer that finishes after the user left it out of the next conversation", async () => {
    const replaceState = vi.spyOn(window.history, "replaceState");
    renderPage(null);
    askWithKeyboard("Vilken gräns gäller?");
    await screen.findByRole("log", { name: "Konversation" });
    await waitFor(() => expect(spies.streams).toHaveLength(1));

    fireEvent.click(screen.getAllByRole("button", { name: "Ny konversation" })[0]!);
    await waitFor(() => expect(screen.queryByRole("log")).toBeNull());

    await act(async () => answer(spies.streams[0]!, "session-old", "Gammalt svar"));
    // The left conversation still gets its title (the history lists it)…
    await waitFor(() => expect(spies.titled).toEqual(["session-old"]));
    // …but the new one keeps its URL, heading and silence.
    expect(replaceState).not.toHaveBeenCalledWith(null, "", "/chat?session_id=session-old");
    expect(spies.announce).not.toHaveBeenCalledWith("Svaret är klart");
    expect(h1Texts()).toEqual(["Upphandlingsassistenten"]);
    expect(screen.queryByText("Gammalt svar")).toBeNull();
  });

  it("keeps this visit's turns when switching to Insikter and back", async () => {
    renderPage(null, { ...partner, insightEnabled: true });
    askWithKeyboard("Vilken gräns gäller?");
    await waitFor(() => expect(spies.streams).toHaveLength(1));
    await act(async () => answer(spies.streams[0]!, "session-1", "Gränsen är 700 000 kr."));
    const log = await screen.findByRole("log", { name: "Konversation" });
    expect(await within(log).findByText("Gränsen är 700 000 kr.")).toBeTruthy();

    fireEvent.click(screen.getByRole("radio", { name: "Insikter" }));
    expect(await screen.findByText("Totala konversationer")).toBeTruthy();
    expect(screen.queryByRole("log")).toBeNull();

    fireEvent.click(screen.getByRole("radio", { name: "Chatt" }));
    expect(within(screen.getByRole("log")).getByText("Gränsen är 700 000 kr.")).toBeTruthy();
    expect(within(screen.getByRole("log")).getByText("Vilken gräns gäller?")).toBeTruthy();
  });

  it("returns a first question that fails before it is sent to the start composer", async () => {
    const failure = deferred();
    spies.failAfter = failure.promise;
    renderPage(null);
    askWithKeyboard("Vilken gräns gäller?");
    await screen.findByRole("log", { name: "Konversation" });
    // The docked composer took over, focus followed it.
    await waitFor(() => expect(document.activeElement).toBe(composer()));

    await act(async () => failure.resolve());
    await waitFor(() => expect(screen.queryByRole("log")).toBeNull());
    expect(await screen.findByText("Tjänsten svarar inte")).toBeTruthy();
    // One h1 (the start state's), the question back in the composer, focus with it.
    expect(h1Texts()).toEqual(["Upphandlingsassistenten"]);
    expect(composer().value).toBe("Vilken gräns gäller?");
    await waitFor(() => expect(document.activeElement).toBe(composer()));
  });
});
