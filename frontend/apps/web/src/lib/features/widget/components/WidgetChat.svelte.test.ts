/* eslint-disable eneo/no-raw-color -- fixtures use literal widget colours */
import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";
import type { WidgetPublicConfig } from "@eneo/eneo-js";
import "../../../../app.css";

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
  sessions: 0
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
        get: unsupported,
        leaveFeedback: async (args: unknown) => {
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

async function releaseAnswer() {
  await vi.waitFor(() => expect(fake.release).not.toBeNull());
  const release = fake.release!;
  fake.release = null;
  release();
  await expect.element(page.getByText("Svaret från assistenten.")).toBeVisible();
}

beforeEach(() => {
  fake.asks.length = 0;
  fake.feedback.length = 0;
  fake.release = null;
  fake.sessions = 0;
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
