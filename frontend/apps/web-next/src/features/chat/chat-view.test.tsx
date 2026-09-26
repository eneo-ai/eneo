// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatPartner, EneoUIMessage } from "@/lib/chat/types";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { ChatView, type ActivityState } from "./chat-view";

const spies = vi.hoisted(() => ({ announce: vi.fn(), toastError: vi.fn() }));

const api = vi.hoisted(() => ({
  GET: vi.fn(async (path: string) => {
    if (path === "/api/v1/dashboard/") {
      return {
        data: {
          spaces: {
            items: [
              {
                id: "space-1",
                name: "Upphandling",
                personal: false,
                organization: false,
                applications: {
                  assistants: {
                    items: [{ id: "assistant-9", name: "Upphandlingsassistenten", icon_id: null }]
                  }
                }
              }
            ]
          }
        },
        response: new Response()
      };
    }
    return { data: undefined, error: { message: "unexpected" }, response: new Response() };
  }),
  POST: vi.fn(async () => ({ data: undefined, response: new Response() })),
  PUT: vi.fn(async (_path: string, init: { body: unknown }) => ({
    data: init.body,
    response: new Response()
  })),
  DELETE: vi.fn(async () => ({ data: undefined, response: new Response(null, { status: 204 }) })),
  PATCH: vi.fn()
}));

vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("next/navigation", () => import("@/test/navigation"));
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

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const personal: ChatPartner = {
  type: "default-assistant",
  id: "personal-1",
  name: "Personlig assistent"
};

const assistant: ChatPartner = {
  type: "assistant",
  id: "assistant-1",
  name: "Upphandlingsassistenten",
  description: "Granskar upphandlingar mot LOU."
};

const history: EneoUIMessage[] = [
  { id: "m1-q", role: "user", parts: [{ type: "text", text: "Vad gäller?" }] },
  {
    id: "m1",
    role: "assistant",
    parts: [{ type: "text", text: "Direktupphandlingsgränsen är 700 000 kr.", state: "done" }]
  }
];

function Harness({
  partner,
  messages = [],
  sessionId = null
}: {
  partner: ChatPartner;
  messages?: EneoUIMessage[];
  sessionId?: string | null;
}) {
  const [activity, setActivity] = useState<ActivityState | null>(null);
  return (
    <div className="flex h-[600px] flex-col">
      <ChatView
        partner={partner}
        initialMessages={messages}
        initialSessionId={sessionId}
        activity={activity}
        onActivityChange={setActivity}
      />
    </div>
  );
}

describe("ChatView start state", () => {
  it("greets the user, fills the composer from a starter card and links their assistants", async () => {
    renderInApp(<Harness partner={personal} />);
    expect(
      screen.getByRole("heading", { level: 1, name: /^God (morgon|dag|kväll), Anna$/ })
    ).toBeTruthy();

    const textarea = screen.getByRole("textbox", { name: "Meddelande till Personlig assistent" });
    fireEvent.click(screen.getByRole("button", { name: /Gör en plan/ }));
    expect((textarea as HTMLTextAreaElement).value).toBe("Gör en konkret plan för: ");
    expect(document.activeElement).toBe(textarea);

    const quickLinks = await screen.findByRole("region", { name: "Dina assistenter" });
    const link = within(quickLinks).getByRole("link", { name: /Upphandlingsassistenten/ });
    expect(link.getAttribute("href")).toBe("/spaces/space-1/chat?type=assistant&id=assistant-9");
    expect(within(quickLinks).getByRole("link", { name: "Visa alla" })).toBeTruthy();
  });

  it("introduces other assistants by name and description", () => {
    renderInApp(<Harness partner={assistant} />);
    expect(screen.getByRole("heading", { level: 1, name: "Upphandlingsassistenten" })).toBeTruthy();
    expect(screen.getByText("Granskar upphandlingar mot LOU.")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Dina assistenter" })).toBeNull();
  });

  it("has no axe violations", async () => {
    const { container } = renderInApp(<Harness partner={personal} />);
    await screen.findByRole("region", { name: "Dina assistenter" });
    await expectNoAxeViolations(container);
  });
});

describe("ChatView conversation", () => {
  it("names the message list and keeps it out of live announcements", () => {
    renderInApp(<Harness partner={assistant} messages={history} sessionId="session-1" />);
    const log = screen.getByRole("log", { name: "Konversation" });
    expect(log.getAttribute("aria-live")).toBe("off");
    expect(within(log).getByRole("article", { name: "Ditt meddelande" })).toBeTruthy();
    expect(
      within(log).getByRole("article", { name: /svar från upphandlingsassistenten/i })
    ).toBeTruthy();
    // Answer text never sits in a live region (announcements go through
    // Astryx useAnnounce instead of reading streamed tokens).
    const answerText = within(log).getByText("Direktupphandlingsgränsen är 700 000 kr.");
    expect(answerText.closest('[aria-live]:not([aria-live="off"])')).toBeNull();
    expect(screen.getByRole("button", { name: "Skicka meddelande" })).toBeTruthy();
  });

  it("has no axe violations", async () => {
    const { container } = renderInApp(
      <Harness partner={assistant} messages={history} sessionId="session-1" />
    );
    await waitFor(() => expect(screen.getByRole("log")).toBeTruthy());
    await expectNoAxeViolations(container);
  });
});

/** A saved conversation of two answers; the first was rated good. */
const ratedHistory: EneoUIMessage[] = [
  { id: "m1-q", role: "user", parts: [{ type: "text", text: "Vad gäller?" }] },
  {
    id: "m1",
    role: "assistant",
    parts: [{ type: "text", text: "Direktupphandlingsgränsen är 700 000 kr.", state: "done" }],
    metadata: { feedback: 1 }
  },
  { id: "m2-q", role: "user", parts: [{ type: "text", text: "Gäller det kommuner?" }] },
  {
    id: "m2",
    role: "assistant",
    parts: [{ type: "text", text: "Ja, även kommuner.", state: "done" }],
    metadata: { feedback: null }
  }
];

const FEEDBACK_PATH = "/api/v1/conversations/{session_id}/messages/{message_id}/feedback/";

/** The rating controls of the n-th answer. */
function ratingOf(answer: number) {
  const group = screen.getAllByRole("group", { name: "Betygsätt svaret" })[answer]!;
  return {
    group,
    good: within(group).getByRole("button", { name: "Bra svar" }),
    bad: within(group).getByRole("button", { name: "Dåligt svar" })
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe("ChatView answer feedback", () => {
  it("offers a rating on every answer, restored from the saved conversation", () => {
    renderInApp(<Harness partner={assistant} messages={ratedHistory} sessionId="session-1" />);

    expect(screen.getAllByRole("group", { name: "Betygsätt svaret" })).toHaveLength(2);
    const first = ratingOf(0);
    expect(first.good.getAttribute("aria-pressed")).toBe("true");
    expect(first.bad.getAttribute("aria-pressed")).toBe("false");
    const second = ratingOf(1);
    expect(second.good.getAttribute("aria-pressed")).toBe("false");
    expect(second.bad.getAttribute("aria-pressed")).toBe("false");
  });

  it("has no rating before the conversation is saved", () => {
    renderInApp(<Harness partner={assistant} messages={ratedHistory} sessionId={null} />);
    expect(screen.queryByRole("group", { name: "Betygsätt svaret" })).toBeNull();
  });

  it("rates one answer from the keyboard, keeps focus and announces the saved rating", async () => {
    const save = deferred<{ data: unknown; response: Response }>();
    api.PUT.mockImplementationOnce(() => save.promise);
    renderInApp(<Harness partner={assistant} messages={ratedHistory} sessionId="session-1" />);
    const { bad, good } = ratingOf(1);

    // Both thumbs are plain buttons in the tab order; Enter or Space presses them.
    expect(bad.tabIndex).toBe(0);
    bad.focus();
    fireEvent.click(bad);

    // Shown before the save is done, and still enabled and focused meanwhile.
    await waitFor(() => expect(bad.getAttribute("aria-pressed")).toBe("true"));
    expect(bad.hasAttribute("disabled")).toBe(false);
    expect(document.activeElement).toBe(bad);
    expect(api.PUT).toHaveBeenCalledWith(FEEDBACK_PATH, {
      params: { path: { session_id: "session-1", message_id: "m2" } },
      body: { value: -1 }
    });
    expect(spies.announce).not.toHaveBeenCalled();

    await act(async () =>
      save.resolve({ data: { value: -1, text: null }, response: new Response() })
    );
    await waitFor(() => expect(spies.announce).toHaveBeenCalledWith("Tack för din återkoppling"));
    expect(document.activeElement).toBe(bad);
    expect(good.getAttribute("aria-pressed")).toBe("false");
    // The other answer keeps its own rating.
    expect(ratingOf(0).good.getAttribute("aria-pressed")).toBe("true");
  });

  it("clears a rating by pressing the chosen thumb again", async () => {
    renderInApp(<Harness partner={assistant} messages={ratedHistory} sessionId="session-1" />);
    const { good } = ratingOf(0);

    fireEvent.click(good);

    await waitFor(() => expect(good.getAttribute("aria-pressed")).toBe("false"));
    expect(api.DELETE).toHaveBeenCalledWith(FEEDBACK_PATH, {
      params: { path: { session_id: "session-1", message_id: "m1" } }
    });
    await waitFor(() =>
      expect(spies.announce).toHaveBeenCalledWith("Din återkoppling har tagits bort")
    );
  });

  it("switches a rating in one press", async () => {
    renderInApp(<Harness partner={assistant} messages={ratedHistory} sessionId="session-1" />);
    const { good, bad } = ratingOf(0);

    fireEvent.click(bad);

    await waitFor(() => expect(bad.getAttribute("aria-pressed")).toBe("true"));
    expect(good.getAttribute("aria-pressed")).toBe("false");
    await waitFor(() => expect(spies.announce).toHaveBeenCalledWith("Tack för din återkoppling"));
    expect(api.PUT).toHaveBeenCalledTimes(1);
    expect(api.DELETE).not.toHaveBeenCalled();
  });

  it("goes back to the saved rating and shows an error when saving fails", async () => {
    api.PUT.mockImplementationOnce(async () => ({
      data: undefined,
      error: { message: "Tjänsten svarar inte" },
      response: new Response(null, { status: 500 })
    }));
    renderInApp(<Harness partner={assistant} messages={ratedHistory} sessionId="session-1" />);
    const { good, bad } = ratingOf(0);

    fireEvent.click(bad);

    await waitFor(() => expect(spies.toastError).toHaveBeenCalledTimes(1));
    expect(bad.getAttribute("aria-pressed")).toBe("false");
    expect(good.getAttribute("aria-pressed")).toBe("true");
    expect(spies.announce).not.toHaveBeenCalled();
  });

  it("saves presses made during a save one after another", async () => {
    const first = deferred<{ data: unknown; response: Response }>();
    api.PUT.mockImplementationOnce(() => first.promise);
    renderInApp(<Harness partner={assistant} messages={ratedHistory} sessionId="session-1" />);
    const { good } = ratingOf(1);

    fireEvent.click(good);
    await waitFor(() => expect(good.getAttribute("aria-pressed")).toBe("true"));
    fireEvent.click(good);

    // The second press shows before the first save is done, and waits for it.
    await waitFor(() => expect(good.getAttribute("aria-pressed")).toBe("false"));
    expect(api.DELETE).not.toHaveBeenCalled();
    await act(async () => first.resolve({ data: { value: 1 }, response: new Response() }));
    await waitFor(() => expect(api.DELETE).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(spies.announce).toHaveBeenLastCalledWith("Din återkoppling har tagits bort")
    );
    expect(good.getAttribute("aria-pressed")).toBe("false");
  });

  it("has no axe violations with rated answers", async () => {
    const { container } = renderInApp(
      <Harness partner={assistant} messages={ratedHistory} sessionId="session-1" />
    );
    await waitFor(() => expect(screen.getByRole("log")).toBeTruthy());
    await expectNoAxeViolations(container);
  });
});
