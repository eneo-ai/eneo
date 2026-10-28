// @vitest-environment jsdom
import type { WidgetClient, WidgetPublicConfig } from "@eneo/eneo-js";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
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

/** A widget client whose answers arrive as one chunk of text. */
function fakeClient(answer = "Pour over: 15 g kaffe på 250 g vatten.") {
  const leaveFeedback = vi.fn(async () => ({}));
  const ask = vi.fn(
    async ({ question, callbacks }: { question: string; callbacks?: Callbacks }) => {
      const message = {
        id: "m1",
        session_id: SESSION,
        question,
        answer: "",
        files: [],
        generated_files: [],
        references: [],
        tools: { assistants: [] },
        mcp_tool_references: []
      };
      callbacks?.onFirstChunk?.(message as never);
      callbacks?.onText?.({ answer, references: [] } as never);
      return { ...message, answer };
    }
  );
  const client = {
    publicId: PUBLIC_ID,
    challengeUrl: `http://localhost:3100/api/v1/widgets/${PUBLIC_ID}/challenge/`,
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
    expect(screen.getByText("Hej! Fråga mig om kaffe.")).toBeTruthy();
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
