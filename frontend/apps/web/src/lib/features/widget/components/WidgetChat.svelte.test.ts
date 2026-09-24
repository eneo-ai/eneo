/* eslint-disable eneo/no-raw-color -- fixtures use literal widget colours */
import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { EneoError, type WidgetPublicConfig } from "@eneo/eneo-js";
import "../../../../app.css";
import axe, { type AxeResults } from "axe-core";
import { virtual } from "@guidepup/virtual-screen-reader";
import { backgroundOf, contrastAgainst } from "./contrastProbe";

/** Rule ids and targets of every axe violation on the page, for a readable diff. */
async function violations() {
  const result = await axe.run(document, {
    // Contrast needs the widget colours the page computes at runtime.
    rules: { "color-contrast": { enabled: false } }
  });
  return summarise(result);
}

/** Every WCAG 2.0–2.2 A and AA rule, contrast included; any impact counts. */
async function wcagViolations() {
  const result = await axe.run(document, {
    runOnly: {
      type: "tag",
      values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"]
    }
  });
  return summarise(result);
}

function summarise(result: AxeResults) {
  return result.violations.map((v) => ({
    id: v.id,
    impact: v.impact,
    targets: v.nodes.map((n) => n.target.join(" "))
  }));
}

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, () => string>>({}, { get: (_target, key) => () => String(key) })
}));

type AskCall = { question: string; conversationId: string | null | undefined };

// The widget client is replaced by a fake whose `ask` holds the stream until
// the test releases it, so clicks "before the first chunk" can be exercised.
const fake = vi.hoisted(() => ({
  asks: [] as AskCall[],
  feedback: [] as unknown[],
  release: null as null | (() => void),
  sessions: 0,
  // Rejects the next feedback call when set, then clears itself.
  failNextFeedback: false,
  // Rejects the next question when set, then clears itself.
  failNextAsk: false,
  // A stored conversation the fake returns on restore, when set.
  restored: null as null | Record<string, unknown>,
  holdNextRestore: false,
  releaseRestore: null as null | (() => void),
  // Answer texts for the next asks, in order; the default after that.
  answers: [] as string[],
  // The next answer breaks off after its first words, then clears itself.
  breakOffNext: false,
  // Errors the next asks fail with before any chunk, in order.
  askErrors: [] as unknown[],
  // Errors the next restores fail with, in order.
  getErrors: [] as unknown[],
  // Visitor tokens minted so far.
  mints: 0,
  // Merged into every first chunk, and the references every answer cites.
  chunkExtras: {} as Record<string, unknown>,
  references: [] as unknown[]
}));

vi.mock("@eneo/eneo-js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@eneo/eneo-js")>();
  const unsupported = async () => {
    throw new Error("not available to widget visitors");
  };
  return {
    ...actual,
    createWidgetClient: () => ({
      publicId: "wgt_test",
      challengeUrl: "http://localhost/api/v1/widgets/wgt_test/challenge/",
      config: unsupported,
      createVisitorSession: async () => {
        fake.mints += 1;
        return {
          token: "visitor-token",
          expires_in: 3600,
          visitor_id: "11111111-1111-4111-8111-111111111111",
          visitor_key: "key"
        };
      },
      conversations: {
        ask: async ({
          conversation,
          question,
          callbacks
        }: {
          conversation?: { id: string | null };
          question: string;
          callbacks?: {
            onFirstChunk?: (chunk: Record<string, unknown>) => void;
            onText?: (text: Record<string, unknown>) => void;
          };
        }) => {
          fake.asks.push({ question, conversationId: conversation?.id });
          if (fake.failNextAsk) {
            fake.failNextAsk = false;
            throw new Error("boom");
          }
          const failure = fake.askErrors.shift();
          if (failure) throw failure;
          await new Promise<void>((resolve) => {
            fake.release = resolve;
          });
          // A follow-up continues the conversation it was asked in.
          const session_id = conversation?.id || `session-${++fake.sessions}`;
          callbacks?.onFirstChunk?.({
            id: `message-${fake.asks.length}`,
            session_id,
            question,
            answer: "",
            references: [],
            files: [],
            generated_files: [],
            tools: { assistants: [] },
            ...fake.chunkExtras
          });
          const answer = fake.answers.shift();
          if (answer === undefined) {
            // Streamed in two pieces, like a model does.
            callbacks?.onText?.({ answer: "Svaret ", session_id, references: fake.references });
            callbacks?.onText?.({
              answer: "från assistenten.",
              session_id,
              references: fake.references
            });
          } else {
            callbacks?.onText?.({ answer, session_id, references: fake.references });
          }
          if (fake.breakOffNext) {
            fake.breakOffNext = false;
            // Long enough for the streamed words to reach the page first.
            await new Promise((resolve) => setTimeout(resolve, 100));
            throw new actual.EneoError(
              "The AI response stream ended unexpectedly.",
              "SERVER",
              200,
              0
            );
          }
          return {};
        },
        get: async () => {
          const failure = fake.getErrors.shift();
          if (failure) throw failure;
          if (fake.holdNextRestore) {
            fake.holdNextRestore = false;
            await new Promise<void>((resolve) => (fake.releaseRestore = resolve));
          }
          if (!fake.restored) return unsupported();
          return fake.restored;
        },
        leaveFeedback: async (args: unknown) => {
          if (fake.failNextFeedback) {
            fake.failNextFeedback = false;
            throw new Error("boom");
          }
          fake.feedback.push(args);
          return {};
        },
        preflight: async () => ({
          input_tokens: 0,
          file_tokens: 0,
          prompt_tokens: 0,
          assistant_attachment_tokens: 0,
          skill_context_tokens: 0
        }),
        list: async () => ({ items: [], total_count: 0, next_cursor: null }),
        rename: unsupported,
        delete: unsupported,
        approveTools: unsupported,
        getTurnDiagnostics: unsupported,
        getToolCallResult: unsupported
      }
    })
  };
});

import EmbedApp from "./EmbedApp.svelte";

function config(overrides: Partial<WidgetPublicConfig> = {}): WidgetPublicConfig {
  return {
    public_id: "wgt_test",
    name: "Kommunchatten",
    texts: {
      title: "Fråga kommunen",
      subtitle: "Du chattar med en AI-assistent.",
      welcome: "Hej! Vad kan jag hjälpa dig med?",
      suggested_questions: ["Vad har biblioteket för öppettider?"]
    },
    theme: { primary_color: "#1F4E79", radius: 12 },
    language: "sv",
    bot_protection: "none",
    max_question_chars: 2000,
    token_generation: 0,
    show_sources: true,
    show_tool_activity: true,
    collects_feedback_text: true,
    single_turn: false,
    frame_ancestors: [],
    ...overrides
  } as WidgetPublicConfig;
}

function renderApp(
  overrides: Partial<WidgetPublicConfig> = {},
  hostScheme: "light" | "dark" | null = null
) {
  return render(EmbedApp, {
    config: config(overrides),
    publicId: "wgt_test",
    baseUrl: "http://localhost",
    hostOrigin: null,
    hostScheme
  });
}

const suggestion = () => page.getByRole("button", { name: "Vad har biblioteket för öppettider?" });
const composer = () => page.getByRole("textbox", { name: "widget_input_label" });
const answers = () => document.querySelectorAll("[data-widget-chat] [role='log'] li");
/** What the chat's polite live region currently hands a screen reader. */
const announced = () =>
  document.querySelector("[data-widget-chat] [aria-live='polite'][aria-atomic='true']")
    ?.textContent ?? "";

async function releaseAnswer(text = "Svaret från assistenten.") {
  await vi.waitFor(() => expect(fake.release).not.toBeNull());
  const release = fake.release!;
  fake.release = null;
  release();
  // In the log: the live region repeats the answer for screen readers.
  await expect.element(page.getByRole("log").getByText(text).last()).toBeVisible();
}

/** Ask a follow-up through the composer and let its answer arrive. */
async function askFollowUp(question: string, answer: string) {
  fake.answers.push(answer);
  await userEvent.fill(composer(), question);
  await userEvent.keyboard("{Enter}");
  await releaseAnswer(answer);
  await expect.element(composer()).toBeEnabled();
}

function widgetError(status: number, code: string, headers?: Record<string, string>) {
  return new EneoError(
    "failed",
    "SERVER",
    status,
    0,
    { detail: { code } },
    { endpoint: "/x" },
    headers ? new Headers(headers) : undefined
  );
}

/** A visitor who was here before, with a live token and a remembered conversation. */
function rememberVisitor() {
  localStorage.setItem(
    "eneo-widget:wgt_test",
    JSON.stringify({
      visitor_id: "11111111-1111-4111-8111-111111111111",
      visitor_key: "key",
      token: "visitor-token",
      expires_at: Date.now() + 600_000,
      session_id: "session-9"
    })
  );
  fake.restored = {
    id: "session-9",
    name: "Tidigare",
    messages: [
      {
        id: "message-9",
        question: "Hej?",
        answer: "Hej där.",
        references: [],
        files: [],
        tools: { assistants: [] }
      }
    ],
    feedback: null
  };
}

beforeEach(() => {
  fake.asks.length = 0;
  fake.feedback.length = 0;
  fake.release = null;
  fake.sessions = 0;
  fake.restored = null;
  fake.holdNextRestore = false;
  fake.releaseRestore = null;
  fake.failNextFeedback = false;
  fake.failNextAsk = false;
  fake.answers.length = 0;
  fake.breakOffNext = false;
  fake.askErrors.length = 0;
  fake.getErrors.length = 0;
  fake.mints = 0;
  fake.chunkExtras = {};
  fake.references = [];
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

describe("WidgetChat", () => {
  test("repeated suggestion clicks before the first chunk start one ask", async () => {
    renderApp();
    const button = suggestion();
    await expect.element(button).toBeEnabled();
    const element = button.element() as HTMLButtonElement;
    // Two synchronous clicks: the second lands before the DOM disables the button.
    element.click();
    element.click();
    await expect.element(button).toBeDisabled();
    await userEvent.click(button, { force: true });
    await vi.waitFor(() => expect(fake.release).not.toBeNull());
    expect(fake.asks).toHaveLength(1);

    await releaseAnswer();
    expect(fake.asks).toHaveLength(1);
    expect(answers()).toHaveLength(1);
    await expect.element(composer()).toBeEnabled();
    // The stored conversation is remembered and can be rated.
    await expect.element(page.getByText("widget_feedback_prompt")).toBeVisible();
    expect(JSON.parse(localStorage.getItem("eneo-widget:wgt_test")!).session_id).toBe("session-1");
  });

  test("a vote is acknowledged and can carry an optional comment", async () => {
    renderApp();
    await userEvent.click(suggestion());
    await vi.waitFor(() => expect(fake.release).not.toBeNull());
    await releaseAnswer();

    // A negative vote asks what was missing; a positive one asks for more.
    await userEvent.click(page.getByRole("button", { name: "widget_feedback_unhelpful" }));
    await expect.element(page.getByRole("status")).toHaveTextContent("widget_feedback_thanks");
    await expect
      .element(page.getByRole("button", { name: "widget_feedback_more_negative" }))
      .toBeVisible();
    await userEvent.click(page.getByRole("button", { name: "widget_feedback_helpful" }));
    expect(fake.feedback.at(-1)).toEqual({
      conversation: { id: "session-1" },
      feedback: { value: 1 }
    });

    // The comment is opt-in: a link opens a dialog, nothing is asked inline.
    expect(page.getByRole("dialog").elements()).toHaveLength(0);
    await userEvent.click(page.getByRole("button", { name: "widget_feedback_more" }));
    const dialog = page.getByRole("dialog");
    await expect.element(dialog).toBeVisible();
    const send = dialog.getByRole("button", { name: "widget_feedback_send" });
    await expect.element(send).toBeDisabled();
    await userEvent.fill(dialog.getByRole("textbox"), "Svaret saknade öppettider.");
    await userEvent.click(send);

    await expect.element(page.getByRole("status")).toHaveTextContent("widget_feedback_received");
    expect(fake.feedback.at(-1)).toEqual({
      conversation: { id: "session-1" },
      feedback: { value: 1, text: "Svaret saknade öppettider." }
    });
    await vi.waitFor(() => expect(page.getByRole("dialog").elements()).toHaveLength(0));
    expect(page.getByRole("button", { name: "widget_feedback_more" }).elements()).toHaveLength(0);
  });

  test("a failed comment keeps the dialog open and says so inside it", async () => {
    renderApp();
    await userEvent.click(suggestion());
    await vi.waitFor(() => expect(fake.release).not.toBeNull());
    await releaseAnswer();
    await userEvent.click(page.getByRole("button", { name: "widget_feedback_helpful" }));
    await userEvent.click(page.getByRole("button", { name: "widget_feedback_more" }));
    const dialog = page.getByRole("dialog");
    await userEvent.fill(dialog.getByRole("textbox"), "Ett försök.");

    fake.failNextFeedback = true;
    await userEvent.click(dialog.getByRole("button", { name: "widget_feedback_send" }));

    await expect.element(dialog.getByRole("alert")).toHaveTextContent("widget_error_generic");
    await expect.element(dialog).toBeVisible();

    // The text is still there; the next attempt goes through and closes it.
    await userEvent.click(dialog.getByRole("button", { name: "widget_feedback_send" }));
    await expect.element(page.getByRole("status")).toHaveTextContent("widget_feedback_received");
    await vi.waitFor(() => expect(page.getByRole("dialog").elements()).toHaveLength(0));
    expect(fake.feedback.at(-1)).toEqual({
      conversation: { id: "session-1" },
      feedback: { value: 1, text: "Ett försök." }
    });
  });

  test("a restored conversation shows the vote the server remembers", async () => {
    localStorage.setItem(
      "eneo-widget:wgt_test",
      JSON.stringify({
        visitor_id: "11111111-1111-4111-8111-111111111111",
        visitor_key: "key",
        token: "visitor-token",
        expires_at: Date.now() + 600_000,
        session_id: "session-9"
      })
    );
    fake.restored = {
      id: "session-9",
      name: "Tidigare",
      messages: [
        {
          id: "message-9",
          question: "Hej?",
          answer: "Hej där.",
          references: [],
          files: [],
          tools: { assistants: [] }
        }
      ],
      feedback: { value: -1, text: null }
    };
    renderApp();

    await expect
      .element(page.getByRole("button", { name: "widget_feedback_unhelpful" }))
      .toHaveAttribute("aria-pressed", "true");
    await expect.element(page.getByRole("status")).toHaveTextContent("widget_feedback_thanks");
    await expect
      .element(page.getByRole("button", { name: "widget_feedback_more_negative" }))
      .toBeVisible();
    expect(fake.feedback).toHaveLength(0);
  });

  test("a vote survives a follow-up question", async () => {
    renderApp();
    await userEvent.click(suggestion());
    await releaseAnswer();
    const helpful = page.getByRole("button", { name: "widget_feedback_helpful" });
    await userEvent.click(helpful);
    await expect.element(helpful).toHaveAttribute("aria-pressed", "true");

    await askFollowUp("Och på lördagar?", "Lördagar har biblioteket stängt.");

    await expect.element(helpful).toHaveAttribute("aria-pressed", "true");
    await expect.element(page.getByRole("status")).toHaveTextContent("widget_feedback_thanks");
    expect(fake.feedback).toHaveLength(1);
  });

  test("a restored vote the visitor changed stays changed after a follow-up", async () => {
    localStorage.setItem(
      "eneo-widget:wgt_test",
      JSON.stringify({
        visitor_id: "11111111-1111-4111-8111-111111111111",
        visitor_key: "key",
        token: "visitor-token",
        expires_at: Date.now() + 600_000,
        session_id: "session-9"
      })
    );
    fake.restored = {
      id: "session-9",
      name: "Tidigare",
      messages: [
        {
          id: "message-9",
          question: "Hej?",
          answer: "Hej där.",
          references: [],
          files: [],
          tools: { assistants: [] }
        }
      ],
      feedback: { value: -1, text: null }
    };
    renderApp();
    const helpful = page.getByRole("button", { name: "widget_feedback_helpful" });
    const unhelpful = page.getByRole("button", { name: "widget_feedback_unhelpful" });
    await expect.element(unhelpful).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(helpful);
    await expect.element(helpful).toHaveAttribute("aria-pressed", "true");

    await askFollowUp("En fråga till", "Ett svar till.");

    await expect.element(helpful).toHaveAttribute("aria-pressed", "true");
    await expect.element(unhelpful).toHaveAttribute("aria-pressed", "false");
  });

  test("a sent comment stays acknowledged when the vote changes after a follow-up", async () => {
    renderApp();
    await userEvent.click(suggestion());
    await releaseAnswer();
    await userEvent.click(page.getByRole("button", { name: "widget_feedback_unhelpful" }));
    await userEvent.click(page.getByRole("button", { name: "widget_feedback_more_negative" }));
    const dialog = page.getByRole("dialog");
    await userEvent.fill(dialog.getByRole("textbox"), "Fel öppettider.");
    await userEvent.click(dialog.getByRole("button", { name: "widget_feedback_send" }));
    await expect.element(page.getByRole("status")).toHaveTextContent("widget_feedback_received");
    await vi.waitFor(() => expect(page.getByRole("dialog").elements()).toHaveLength(0));

    await askFollowUp("Och på lördagar?", "Lördagar har biblioteket stängt.");
    await userEvent.click(page.getByRole("button", { name: "widget_feedback_helpful" }));

    // The server keeps the stored comment for a vote without text, so the
    // acknowledgement still holds and no second comment is offered.
    expect(fake.feedback.at(-1)).toEqual({
      conversation: { id: "session-1" },
      feedback: { value: 1 }
    });
    await expect.element(page.getByRole("status")).toHaveTextContent("widget_feedback_received");
    expect(page.getByRole("button", { name: /widget_feedback_more/ }).elements()).toHaveLength(0);
  });

  test("the comment dialog closes in the widget's language and leaves focus on the vote", async () => {
    renderApp();
    await userEvent.click(suggestion());
    await releaseAnswer();
    const helpful = page.getByRole("button", { name: "widget_feedback_helpful" });
    await userEvent.click(helpful);
    await userEvent.click(page.getByRole("button", { name: "widget_feedback_more" }));
    const dialog = page.getByRole("dialog");
    await expect.element(dialog.getByRole("button", { name: "close" })).toBeVisible();

    await userEvent.fill(dialog.getByRole("textbox"), "Tydligt svar.");
    await userEvent.keyboard("{Tab}{Tab}{Enter}");

    await vi.waitFor(() => expect(page.getByRole("dialog").elements()).toHaveLength(0));
    await vi.waitFor(() => expect(document.activeElement).toBe(helpful.element()));
  });

  test("an answer that breaks off keeps what arrived and says it is incomplete", async () => {
    renderApp();
    fake.breakOffNext = true;
    fake.answers.push("Biblioteket har öppet ");
    await userEvent.click(suggestion());
    await releaseAnswer("Biblioteket har öppet");

    await expect.element(page.getByRole("alert")).toHaveTextContent("widget_error_incomplete");
    await expect.element(page.getByText("Biblioteket har öppet")).toBeVisible();
    expect(document.querySelector("[data-widget-chat] [role='log']")!.textContent).not.toContain(
      "chat_stream_error_inline"
    );
    // Nothing reads the broken-off answer out as if it were whole.
    expect(announced()).toBe("");
    // The turn exists on the server: it is remembered and can be rated.
    expect(JSON.parse(localStorage.getItem("eneo-widget:wgt_test")!).session_id).toBe("session-1");
    await expect.element(page.getByText("widget_feedback_prompt")).toBeVisible();
  });

  test("a remembered conversation is restored with a fresh token when the old one went stale", async () => {
    rememberVisitor();
    // A pause or a settings change since the last visit makes the stored token stale.
    fake.getErrors.push(widgetError(401, "visitor_token_stale"));
    renderApp();

    await expect.element(page.getByText("Hej där.")).toBeVisible();
    expect(fake.mints).toBe(1);
    expect(JSON.parse(localStorage.getItem("eneo-widget:wgt_test")!).session_id).toBe("session-9");
  });

  test("waits for a remembered conversation before sending a follow-up", async () => {
    rememberVisitor();
    fake.holdNextRestore = true;
    renderApp();
    await vi.waitFor(() => expect(fake.releaseRestore).not.toBeNull());

    await userEvent.fill(composer(), "Följdfråga?");
    await userEvent.keyboard("{Enter}");
    expect(fake.asks).toHaveLength(0);

    fake.releaseRestore?.();
    await expect.element(page.getByText("Hej där.")).toBeVisible();
    await userEvent.keyboard("{Enter}");
    await vi.waitFor(() => expect(fake.asks).toHaveLength(1));
    expect(fake.asks[0].conversationId).toBe("session-9");
    await releaseAnswer();
  });

  test("a question that fails before it reaches the server goes back into the field", async () => {
    renderApp();
    fake.askErrors.push(widgetError(400, "challenge_invalid"));
    await userEvent.fill(composer(), "Vad kostar bygglov?");
    await userEvent.keyboard("{Enter}");

    await expect.element(page.getByRole("alert")).toHaveTextContent("widget_error_verification");
    await expect.element(composer()).toHaveValue("Vad kostar bygglov?");

    // The same text can simply be sent again.
    await userEvent.click(composer());
    await userEvent.keyboard("{Enter}");
    await releaseAnswer();
    expect(fake.asks.map((ask) => ask.question)).toEqual([
      "Vad kostar bygglov?",
      "Vad kostar bygglov?"
    ]);
  });

  test("a full conversation says to start a new one and moves focus there", async () => {
    renderApp();
    await userEvent.click(suggestion());
    await releaseAnswer();

    fake.askErrors.push(widgetError(400, "session_turns_exceeded"));
    await userEvent.fill(composer(), "En fråga för mycket");
    await userEvent.keyboard("{Enter}");

    await expect.element(page.getByRole("alert")).toHaveTextContent("widget_error_session_limit");
    await expect
      .element(page.getByRole("button", { name: "widget_new_conversation" }))
      .toHaveFocus();
    await expect.element(composer()).toHaveValue("En fråga för mycket");
  });

  test("a conversation the server no longer has is replaced by a new one", async () => {
    renderApp();
    await userEvent.click(suggestion());
    await releaseAnswer();

    fake.askErrors.push(widgetError(404, "session_not_owned"));
    await userEvent.fill(composer(), "Och på lördagar?");
    await userEvent.keyboard("{Enter}");

    await expect.element(page.getByRole("alert")).toHaveTextContent("widget_error_session_gone");
    expect(answers()).toHaveLength(0);
    expect(JSON.parse(localStorage.getItem("eneo-widget:wgt_test")!).session_id).toBeNull();
    await expect.element(composer()).toHaveValue("Och på lördagar?");

    await userEvent.click(composer());
    await userEvent.keyboard("{Enter}");
    await vi.waitFor(() => expect(fake.asks).toHaveLength(3));
    // The gone conversation is never asked in again.
    expect(fake.asks[2].conversationId).toBeFalsy();
    await releaseAnswer();
  });

  test("asking the same question again shows it as pending until the answer starts", async () => {
    renderApp();
    await userEvent.click(suggestion());
    await releaseAnswer();
    await expect.element(composer()).toBeEnabled();
    expect(answers()).toHaveLength(1);

    await userEvent.fill(composer(), "Vad har biblioteket för öppettider?");
    await userEvent.keyboard("{Enter}");
    await vi.waitFor(() => expect(fake.release).not.toBeNull());

    // The first answer plus the pending question with its typing indicator.
    await vi.waitFor(() => expect(answers()).toHaveLength(2));
    expect(answers()[1].textContent).toContain("Vad har biblioteket för öppettider?");
    await releaseAnswer();
    expect(answers()).toHaveLength(2);
  });

  test.each([true, false])(
    "shows the sources and the tool activity only when the widget does (%s)",
    async (shown) => {
      fake.chunkExtras = {
        mcp_tool_calls: [
          {
            server_name: "TimeMCP",
            tool_name: "get_current_time",
            arguments: { timezone: "Europe/Stockholm" },
            tool_call_id: "c1",
            result_status: "completed"
          }
        ]
      };
      fake.references = [
        {
          id: "bbbbbbbb-0000-4000-8000-000000000002",
          metadata: { title: "Öppettider.pdf", url: null, embedding_model_id: "em", size: 10 },
          group_id: null,
          website_id: null,
          original_available: true
        }
      ];
      renderApp({ show_sources: shown, show_tool_activity: shown });
      await userEvent.click(suggestion());
      await releaseAnswer();

      const count = shown ? 1 : 0;
      expect(page.getByRole("button", { name: /widget_sources_count/ }).elements()).toHaveLength(
        count
      );
      expect(page.getByRole("group", { name: "widget_activity" }).elements()).toHaveLength(count);
    }
  );

  test("the send arrow sends and hands focus back to the question field", async () => {
    renderApp();
    await userEvent.fill(composer(), "Vad kostar bygglov?");
    await userEvent.click(page.getByRole("button", { name: "widget_send" }));

    await vi.waitFor(() =>
      expect(fake.asks.map((ask) => ask.question)).toEqual(["Vad kostar bygglov?"])
    );
    await expect.element(composer()).toHaveFocus();
    await releaseAnswer();
  });

  describe.each(["light", "dark"] as const)("focus in the %s scheme", (scheme) => {
    const FOCUSABLE =
      "button:not([disabled]), a[href], textarea:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex='-1'])";

    /** Focus every control from the keyboard and check the indicator it shows. */
    async function checkEveryControl(scope: Element) {
      const controls = Array.from(scope.querySelectorAll<HTMLElement>(FOCUSABLE));
      for (const control of controls) {
        // A key press first, so focus counts as keyboard focus.
        await userEvent.keyboard("{Shift}");
        control.focus();
        const name = `${control.tagName} ${control.getAttribute("aria-label") ?? control.textContent?.trim()}`;
        expect(control.matches(":focus-visible"), name).toBe(true);
        // The question field's box carries its indicator.
        const indicator = control.matches(".widget-composer textarea")
          ? control.closest("form")!
          : control;
        // Buttons that transition every property reach their colour later.
        await Promise.all(indicator.getAnimations().map((animation) => animation.finished));
        const style = getComputedStyle(indicator);
        expect(style.outlineStyle, name).not.toBe("none");
        expect(parseFloat(style.outlineWidth), name).toBeGreaterThanOrEqual(2);
        const ratio = contrastAgainst(style.outlineColor, indicator.parentElement);
        expect(ratio, `${name}: ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(3);
      }
      return controls.length;
    }

    test("every control shows an indicator of at least 3:1", async () => {
      renderApp(
        {
          texts: {
            title: "Fråga kommunen",
            subtitle: "Du chattar med en AI-assistent.",
            welcome: "Hej!",
            suggested_questions: ["Vad har biblioteket för öppettider?"],
            footer_text: "Läs mer",
            footer_link_url: "https://www.kommun.se/integritet"
          }
        } as Partial<WidgetPublicConfig>,
        scheme
      );
      const chat = document.querySelector("[data-widget-chat]")!;
      expect(backgroundOf(chat)[0] < 128).toBe(scheme === "dark");
      // Suggestion, question field and footer link.
      expect(await checkEveryControl(chat)).toBeGreaterThanOrEqual(3);

      await userEvent.click(suggestion());
      await releaseAnswer();
      await userEvent.click(page.getByRole("button", { name: "widget_feedback_helpful" }));
      await userEvent.fill(composer(), "En till fråga");
      // New conversation, thumbs, "tell us more", question field, send, footer link.
      expect(await checkEveryControl(chat)).toBeGreaterThanOrEqual(7);

      await userEvent.click(page.getByRole("button", { name: "widget_feedback_more" }));
      const dialog = page.getByRole("dialog");
      await expect.element(dialog).toBeVisible();
      await userEvent.fill(dialog.getByRole("textbox"), "Bra.");
      // Comment field, cancel, send and the close button.
      expect(await checkEveryControl(dialog.element())).toBeGreaterThanOrEqual(4);
    });
  });

  test("the chat, its acknowledgement and the comment dialog pass axe", async () => {
    renderApp();
    await userEvent.click(suggestion());
    await vi.waitFor(() => expect(fake.release).not.toBeNull());
    await releaseAnswer();
    await userEvent.click(page.getByRole("button", { name: "widget_feedback_unhelpful" }));
    await expect.element(page.getByRole("status")).toHaveTextContent("widget_feedback_thanks");
    expect(JSON.stringify(await violations())).toBe("[]");

    await userEvent.click(page.getByRole("button", { name: "widget_feedback_more_negative" }));
    await expect.element(page.getByRole("dialog")).toBeVisible();
    expect(JSON.stringify(await violations())).toBe("[]");
  });

  test("a screen reader hears that the question went off and then every answer", async () => {
    renderApp();
    await userEvent.click(suggestion());
    await vi.waitFor(() => expect(announced()).toBe("assistant_is_typing"));
    // The typing dots themselves stay silent.
    expect(page.getByRole("status", { name: "assistant_is_typing" }).elements()).toHaveLength(0);
    await releaseAnswer();
    await vi.waitFor(() => expect(announced()).toBe("widget_assistant: Svaret från assistenten."));

    // The same answer again is read again: the region is emptied in between.
    await userEvent.fill(composer(), "En följdfråga");
    await userEvent.keyboard("{Enter}");
    await vi.waitFor(() => expect(announced()).toBe("assistant_is_typing"));
    await releaseAnswer();
    await vi.waitFor(() => expect(announced()).toBe("widget_assistant: Svaret från assistenten."));
  });

  test("a short panel scrolls as one page so the composer stays reachable", async () => {
    // A 400 x 220 frame is what the panel gets on a laptop zoomed to 200 %;
    // with a full set of texts the header and composer alone need more.
    const before = { width: window.innerWidth, height: window.innerHeight };
    await page.viewport(400, 220);
    try {
      renderApp({
        texts: {
          title: "Fråga kommunen",
          subtitle:
            "Du chattar med en AI-assistent. Svaren kan innehålla fel – kontrollera viktig information.",
          welcome: "Hej! Vad kan jag hjälpa dig med?",
          suggested_questions: [
            "Vad har biblioteket för öppettider?",
            "Hur ansöker jag om bygglov?",
            "När töms mitt sopkärl?",
            "Var kan jag parkera i centrum?"
          ],
          footer_text: "Läs om hur vi hanterar personuppgifter."
        }
      });
      await expect.element(composer()).toBeVisible();
      const textarea = composer().element() as HTMLElement;
      textarea.scrollIntoView();
      const box = textarea.getBoundingClientRect();
      expect(box.top).toBeGreaterThanOrEqual(0);
      expect(box.bottom).toBeLessThanOrEqual(window.innerHeight);
    } finally {
      await page.viewport(before.width, before.height);
    }
  });

  test("a single-turn widget offers a new question instead of follow-up or feedback", async () => {
    renderApp({ single_turn: true });
    await userEvent.click(suggestion());
    await releaseAnswer();

    const newQuestion = page.getByRole("button", { name: "widget_new_question" });
    await expect.element(newQuestion).toBeVisible();
    await expect.element(newQuestion).toHaveFocus();
    await expect.element(composer()).toBeDisabled();
    expect(document.querySelector("#widget-feedback-prompt")).toBeNull();
    expect(JSON.parse(localStorage.getItem("eneo-widget:wgt_test")!).session_id).toBeNull();

    await userEvent.click(newQuestion);
    await expect.element(composer()).toBeEnabled();
    await expect.element(composer()).toHaveFocus();
    expect(answers()).toHaveLength(0);

    await userEvent.fill(composer(), "En helt ny fråga");
    await userEvent.keyboard("{Enter}");
    await vi.waitFor(() => expect(fake.asks).toHaveLength(2));
    // The deleted session is never sent again.
    expect(fake.asks[1].conversationId).toBeFalsy();
    await releaseAnswer();
    expect(fake.feedback).toHaveLength(0);
  });
});

describe("WidgetChat for screen reader users", () => {
  /** Walk the whole page with the virtual screen reader's reading cursor. */
  async function readThrough(): Promise<string[]> {
    for (let step = 0; step < 100; step++) {
      if ((await virtual.lastSpokenPhrase()) === "end of document") break;
      await virtual.next();
    }
    return virtual.spokenPhraseLog();
  }

  /** What live regions said, not the reading cursor. An emptied region says nothing. */
  async function announcements(): Promise<string[]> {
    return (await virtual.spokenPhraseLog()).filter((phrase) =>
      /^(polite|assertive): \S/.test(phrase)
    );
  }

  test("reads the title, the AI disclosure and a labelled composer in landmarks", async () => {
    renderApp();
    await expect.element(composer()).toBeVisible();
    await virtual.start({ container: document.body });
    try {
      expect(await readThrough()).toEqual([
        "document",
        "banner",
        "heading, Fråga kommunen, level 1",
        "paragraph",
        "Du chattar med en AI-assistent.",
        "end of paragraph",
        "end of banner",
        "main",
        "paragraph",
        "Hej! Vad kan jag hjälpa dig med?",
        "end of paragraph",
        "end of main",
        "contentinfo",
        "list, widget_suggested_questions",
        "listitem, level 1, position 1, set size 1",
        "button, Vad har biblioteket för öppettider?",
        "end of listitem, level 1, position 1, set size 1",
        "end of list, widget_suggested_questions",
        "form",
        "widget_input_label",
        "textbox, widget_input_label, placeholder widget_input_placeholder",
        "button, widget_send, disabled",
        "end of form",
        "end of contentinfo",
        "end of document"
      ]);
    } finally {
      await virtual.stop();
    }
  });

  test("announces each question and every answer once, never the stream", async () => {
    renderApp();
    await expect.element(composer()).toBeVisible();
    await virtual.start({ container: document.body });
    try {
      await userEvent.click(suggestion());
      await vi.waitFor(async () =>
        expect(await announcements()).toEqual(["polite: assistant_is_typing"])
      );
      await releaseAnswer();
      await vi.waitFor(async () =>
        expect(await announcements()).toEqual([
          "polite: assistant_is_typing",
          "polite: widget_assistant: Svaret från assistenten."
        ])
      );

      // The same answer again is announced again.
      await userEvent.fill(composer(), "En följdfråga");
      await userEvent.keyboard("{Enter}");
      await vi.waitFor(async () => expect(await announcements()).toHaveLength(3));
      await releaseAnswer();
      await vi.waitFor(async () =>
        expect(await announcements()).toEqual([
          "polite: assistant_is_typing",
          "polite: widget_assistant: Svaret från assistenten.",
          "polite: assistant_is_typing",
          "polite: widget_assistant: Svaret från assistenten."
        ])
      );
    } finally {
      await virtual.stop();
    }
  });

  test("a failed question is an alert that no pending announcement follows", async () => {
    renderApp();
    await expect.element(composer()).toBeVisible();
    await virtual.start({ container: document.body });
    try {
      fake.failNextAsk = true;
      await userEvent.click(suggestion());
      // Screen readers read an alert as it appears (the virtual one does not
      // model that), so the role is what matters here.
      await expect.element(page.getByRole("alert")).toHaveTextContent("widget_error_generic");
      await new Promise((resolve) => setTimeout(resolve, 300));
      expect(await announcements()).toEqual([]);
    } finally {
      await virtual.stop();
    }
  });

  test("announces the acknowledgement of a vote", async () => {
    renderApp();
    await userEvent.click(suggestion());
    await releaseAnswer();
    await virtual.start({ container: document.body });
    try {
      await userEvent.click(page.getByRole("button", { name: "widget_feedback_helpful" }));
      await vi.waitFor(async () =>
        expect(await announcements()).toContain("polite: widget_feedback_thanks")
      );
    } finally {
      await virtual.stop();
    }
  });
});

describe("WidgetChat against WCAG 2.2 A and AA", () => {
  test.each(["light", "dark"] as const)(
    "the empty and the answered chat pass every rule, contrast included (%s)",
    async (scheme) => {
      render(EmbedApp, {
        config: config(),
        publicId: "wgt_test",
        baseUrl: "http://localhost",
        hostOrigin: null,
        hostScheme: scheme
      });
      await expect.element(composer()).toBeVisible();
      expect(document.documentElement.dataset.theme).toBe(scheme);
      expect(JSON.stringify(await wcagViolations())).toBe("[]");

      await userEvent.click(suggestion());
      await releaseAnswer();
      await expect.element(page.getByText("widget_feedback_prompt")).toBeVisible();
      expect(JSON.stringify(await wcagViolations())).toBe("[]");
    }
  );

  test("an error and the single-turn follow-up pass every rule", async () => {
    renderApp({ single_turn: true });
    fake.failNextAsk = true;
    await userEvent.click(suggestion());
    await expect.element(page.getByRole("alert")).toHaveTextContent("widget_error_generic");
    expect(JSON.stringify(await wcagViolations())).toBe("[]");

    await userEvent.click(suggestion());
    await releaseAnswer();
    await expect.element(page.getByRole("button", { name: "widget_new_question" })).toBeVisible();
    expect(JSON.stringify(await wcagViolations())).toBe("[]");
  });
});

describe("WidgetChat when text is enlarged or spaced out", () => {
  /** Texts as long as real widgets carry them. */
  const fullTexts = {
    title: "Fråga Sundsvalls kommun om bygglov och tillstånd",
    subtitle:
      "Du chattar med en AI-assistent. Svaren kan innehålla fel – kontrollera viktig information.",
    welcome: "Hej! Vad kan jag hjälpa dig med?",
    suggested_questions: [
      "Vad har biblioteket för öppettider?",
      "Hur ansöker jag om bygglov?",
      "När töms mitt sopkärl?",
      "Var kan jag parkera i centrum?"
    ],
    footer_text: "Läs om hur vi hanterar personuppgifter."
  };

  /** Elements that cut off their own content (overflow hidden or clip, content larger than the box). */
  function clipped(root: Element): string[] {
    const cuts = (value: string) => value === "hidden" || value === "clip";
    return Array.from(root.querySelectorAll<HTMLElement>("*"))
      .filter((element) => {
        // Visually hidden on purpose.
        if (element.closest(".sr-only")) return false;
        const style = getComputedStyle(element);
        return (
          (cuts(style.overflowX) && element.scrollWidth > element.clientWidth + 1) ||
          (cuts(style.overflowY) && element.scrollHeight > element.clientHeight + 1)
        );
      })
      .map((element) => element.outerHTML.slice(0, 80));
  }

  /** Nothing scrolls sideways and nothing is cut off; the composer can be reached. */
  async function expectReadable() {
    const chat = document.querySelector("[data-widget-chat]")!;
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(window.innerWidth);
    expect(chat.scrollWidth).toBeLessThanOrEqual(chat.clientWidth);
    expect(clipped(chat)).toEqual([]);
    const textarea = composer().element() as HTMLElement;
    textarea.scrollIntoView();
    const box = textarea.getBoundingClientRect();
    expect(box.top).toBeGreaterThanOrEqual(0);
    expect(box.bottom).toBeLessThanOrEqual(window.innerHeight);
  }

  async function atViewport(width: number, height: number, body: () => Promise<void>) {
    const before = { width: window.innerWidth, height: window.innerHeight };
    await page.viewport(width, height);
    try {
      await body();
    } finally {
      await page.viewport(before.width, before.height);
    }
  }

  test("reflows at 320 px without scrolling sideways (1.4.10)", async () => {
    await atViewport(320, 480, async () => {
      renderApp({ texts: fullTexts });
      await expect.element(composer()).toBeVisible();
      await expectReadable();
      await userEvent.click(suggestion());
      await releaseAnswer();
      await expectReadable();
    });
  });

  test("keeps everything readable with WCAG text spacing (1.4.12)", async () => {
    // The spacing 1.4.12 requires content to survive, applied to everything.
    const spacing = document.createElement("style");
    spacing.textContent = `
      * { line-height: 1.5 !important; letter-spacing: 0.12em !important; word-spacing: 0.16em !important; }
      p { margin-bottom: 2em !important; }
    `;
    document.head.appendChild(spacing);
    try {
      await atViewport(400, 700, async () => {
        renderApp({ texts: fullTexts });
        await expect.element(composer()).toBeVisible();
        await expectReadable();
        await userEvent.click(suggestion());
        await releaseAnswer();
        await expectReadable();
      });
    } finally {
      spacing.remove();
    }
  });
});
