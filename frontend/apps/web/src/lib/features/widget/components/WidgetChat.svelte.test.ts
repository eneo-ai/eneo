/* eslint-disable eneo/no-raw-color -- fixtures use literal widget colours */
import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";
import type { WidgetPublicConfig } from "@eneo/eneo-js";
import "../../../../app.css";
import axe from "axe-core";

/** Rule ids and targets of every axe violation on the page, for a readable diff. */
async function violations() {
  const result = await axe.run(document, {
    // Contrast needs the widget colours the page computes at runtime.
    rules: { "color-contrast": { enabled: false } }
  });
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
  // A stored conversation the fake returns on restore, when set.
  restored: null as null | Record<string, unknown>
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
      createVisitorSession: async () => ({
        token: "visitor-token",
        expires_in: 3600,
        visitor_id: "11111111-1111-4111-8111-111111111111",
        visitor_key: "key"
      }),
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
          await new Promise<void>((resolve) => {
            fake.release = resolve;
          });
          const session_id = `session-${++fake.sessions}`;
          callbacks?.onFirstChunk?.({
            id: `message-${fake.sessions}`,
            session_id,
            question,
            answer: "",
            references: [],
            files: [],
            generated_files: [],
            tools: { assistants: [] }
          });
          callbacks?.onText?.({ answer: "Svaret från assistenten.", session_id, references: [] });
          return {};
        },
        get: async () => {
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

function renderApp(overrides: Partial<WidgetPublicConfig> = {}) {
  return render(EmbedApp, {
    config: config(overrides),
    publicId: "wgt_test",
    baseUrl: "http://localhost",
    hostOrigin: null,
    hostScheme: null
  });
}

const suggestion = () => page.getByRole("button", { name: "Vad har biblioteket för öppettider?" });
const composer = () => page.getByRole("textbox", { name: "widget_input_label" });
const answers = () => document.querySelectorAll("[data-widget-chat] [role='log'] li");
/** What the chat's polite live region currently hands a screen reader. */
const announced = () =>
  document.querySelector("[data-widget-chat] [aria-live='polite'][aria-atomic='true']")
    ?.textContent ?? "";

async function releaseAnswer() {
  await vi.waitFor(() => expect(fake.release).not.toBeNull());
  const release = fake.release!;
  fake.release = null;
  release();
  // In the log: the live region repeats the answer for screen readers.
  await expect
    .element(page.getByRole("log").getByText("Svaret från assistenten.").last())
    .toBeVisible();
}

beforeEach(() => {
  fake.asks.length = 0;
  fake.feedback.length = 0;
  fake.release = null;
  fake.sessions = 0;
  fake.restored = null;
  fake.failNextFeedback = false;
  localStorage.clear();
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
