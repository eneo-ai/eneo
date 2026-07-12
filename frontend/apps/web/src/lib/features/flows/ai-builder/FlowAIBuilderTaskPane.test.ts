// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it } from "vitest";

import { m } from "$lib/paraglide/messages";

import FlowAIBuilderTaskPane from "./FlowAIBuilderTaskPane.svelte";
import type { ChatMessage, RequirementsSummary } from "./protocol";

globalThis.requestAnimationFrame ??= ((cb: FrameRequestCallback) =>
  setTimeout(() => cb(0), 0)) as never;

afterEach(() => {
  cleanup();
});

const requirements: RequirementsSummary = {
  requirements_version: "v1",
  summary: "Skapa ett beslutsunderlag som PDF.",
  key_decisions: [
    { topic: "Slutresultat", decision: "PDF-dokument" },
    { topic: "Omfattning", decision: "Ett underlag per körning" }
  ],
  input_description: "Text vid körning",
  output_description: "PDF med rekommendation",
  assumptions: ["Svenska som språk", "En körning i taget"],
  manual_setup_notes: []
};

function message(role: "user" | "assistant", content: string): ChatMessage {
  return { role, content, timestamp: 0 };
}

/** Accessible-name matcher for triggers whose label contains regex metachars. */
function nameContaining(label: string): RegExp {
  return new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
}

const conversation: ChatMessage[] = [
  message("user", "Sammanfatta rapporter till en PDF"),
  message("assistant", "Vilket format vill du ha?"),
  message("user", "PDF"),
  message("assistant", "Här är mitt förslag:")
];

describe("FlowAIBuilderTaskPane", () => {
  it("renders the task, definition grid and decisions from the answers", () => {
    render(FlowAIBuilderTaskPane, {
      taskText: "Sammanfatta rapporter till en PDF",
      requirements,
      messages: conversation
    });

    expect(screen.getByRole("heading", { name: m.ai_builder_task_heading() })).toBeTruthy();
    // The task text also appears inside the (closed) conversation log.
    expect(screen.getAllByText("Sammanfatta rapporter till en PDF").length).toBeGreaterThan(0);

    // Syfte / Indata / Resultat definition rows
    expect(screen.getByText(m.ai_builder_task_purpose())).toBeTruthy();
    expect(screen.getByText("Skapa ett beslutsunderlag som PDF.")).toBeTruthy();
    expect(screen.getByText(m.ai_builder_requirements_input())).toBeTruthy();
    expect(screen.getByText("Text vid körning")).toBeTruthy();
    expect(screen.getByText(m.ai_builder_task_result())).toBeTruthy();
    expect(screen.getByText("PDF med rekommendation")).toBeTruthy();

    expect(
      screen.getByRole("heading", { name: m.ai_builder_decisions_from_answers() })
    ).toBeTruthy();
    expect(screen.getByText("Slutresultat")).toBeTruthy();
    expect(screen.getByText("PDF-dokument")).toBeTruthy();
  });

  it("clamps a long task behind an expander that reports the character count", async () => {
    const longTask = "Sammanfatta rapporterna. ".repeat(20).trim();
    render(FlowAIBuilderTaskPane, {
      taskText: longTask,
      requirements: null,
      messages: []
    });

    const expander = screen.getByRole("button", {
      name: m.ai_builder_task_expand({ count: longTask.length.toLocaleString("sv-SE") })
    });
    expect(expander.getAttribute("aria-expanded")).toBe("false");

    await fireEvent.click(expander);
    expect(expander.getAttribute("aria-expanded")).toBe("true");
    expect(expander.textContent?.trim()).toBe(m.ai_builder_task_collapse());
  });

  it("shows no expander for a short task", () => {
    render(FlowAIBuilderTaskPane, {
      taskText: "Kort uppgift",
      requirements: null,
      messages: []
    });

    expect(screen.queryByRole("button", { name: /tecken|characters/ })).toBeNull();
  });

  it("collapses assumptions and the conversation into independent sections", async () => {
    render(FlowAIBuilderTaskPane, {
      taskText: "Sammanfatta rapporter till en PDF",
      requirements,
      messages: conversation
    });

    const assumptionsTrigger = screen.getByRole("button", {
      name: nameContaining(`${m.ai_builder_assumptions()} (2)`)
    });
    expect(assumptionsTrigger.getAttribute("aria-expanded")).toBe("false");
    await fireEvent.click(assumptionsTrigger);
    expect(assumptionsTrigger.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("Svenska som språk")).toBeTruthy();

    const conversationTrigger = screen.getByRole("button", {
      name: nameContaining(m.ai_builder_conversation_heading({ count: 4 }))
    });
    expect(conversationTrigger.getAttribute("aria-expanded")).toBe("false");
    await fireEvent.click(conversationTrigger);

    const log = screen.getByRole("log");
    expect(log.getAttribute("aria-label")).toBe(m.ai_builder_conversation_aria());
    expect(log.getAttribute("tabindex")).toBe("0");
    expect(screen.getByText("Vilket format vill du ha?")).toBeTruthy();
    // Assumptions stayed open — sections are independent, not an accordion.
    expect(assumptionsTrigger.getAttribute("aria-expanded")).toBe("true");
  });

  it("windows a long conversation behind 'Visa äldre'", async () => {
    const many = Array.from({ length: 25 }, (_, i) =>
      message(i % 2 === 0 ? "user" : "assistant", `Meddelande ${i + 1}`)
    );
    render(FlowAIBuilderTaskPane, {
      taskText: "Uppgift",
      requirements: null,
      messages: many
    });

    await fireEvent.click(
      screen.getByRole("button", {
        name: nameContaining(m.ai_builder_conversation_heading({ count: 25 }))
      })
    );

    expect(screen.queryByText("Meddelande 1")).toBeNull();
    expect(screen.getByText("Meddelande 25")).toBeTruthy();

    await fireEvent.click(
      screen.getByRole("button", { name: m.ai_builder_conversation_show_older({ count: 5 }) })
    );
    expect(screen.getByText("Meddelande 1")).toBeTruthy();
  });

  it("counts unseen messages while closed and marks them NYTT on reopen", async () => {
    const { rerender } = render(FlowAIBuilderTaskPane, {
      taskText: "Uppgift",
      requirements: null,
      messages: conversation
    });

    const trigger = () =>
      screen.getByRole("button", {
        name: nameContaining(m.ai_builder_conversation_heading({ count: 4 }))
      });

    // Open once (everything counts as seen), then close.
    await fireEvent.click(trigger());
    await fireEvent.click(trigger());

    await rerender({
      taskText: "Uppgift",
      requirements: null,
      messages: [...conversation, message("assistant", "Planen är uppdaterad.")]
    });

    expect(screen.getByText(m.ai_builder_conversation_new_one())).toBeTruthy();

    await fireEvent.click(
      screen.getByRole("button", {
        name: nameContaining(m.ai_builder_conversation_heading({ count: 5 }))
      })
    );
    expect(screen.getByText(m.ai_builder_conversation_new_divider())).toBeTruthy();
    expect(screen.queryByText(m.ai_builder_conversation_new_one())).toBeNull();
  });

  it("keeps the NYTT divider correct when empty assistant envelopes are interleaved", async () => {
    // Plan/status envelopes have no visible content and are filtered from the
    // log; unseen bookkeeping must follow the FILTERED sequence.
    const withEnvelope: ChatMessage[] = [
      message("user", "Sammanfatta rapporter till en PDF"),
      message("assistant", ""),
      message("assistant", "Här är mitt förslag:")
    ];
    const { rerender } = render(FlowAIBuilderTaskPane, {
      taskText: "Uppgift",
      requirements: null,
      messages: withEnvelope
    });

    const trigger = (count: number) =>
      screen.getByRole("button", {
        name: nameContaining(m.ai_builder_conversation_heading({ count }))
      });

    await fireEvent.click(trigger(2));
    await fireEvent.click(trigger(2));

    await rerender({
      taskText: "Uppgift",
      requirements: null,
      messages: [
        ...withEnvelope,
        message("assistant", ""),
        message("assistant", "Uppdaterad plan.")
      ]
    });

    // Exactly ONE visible message is new despite two raw messages arriving.
    expect(screen.getByText(m.ai_builder_conversation_new_one())).toBeTruthy();

    await fireEvent.click(trigger(3));
    const divider = screen.getByText(m.ai_builder_conversation_new_divider());
    expect(divider).toBeTruthy();
    // The divider sits immediately before the new visible message.
    const dividerRow = divider.closest(".new-divider");
    const nextEntry = dividerRow?.nextElementSibling;
    expect(nextEntry?.textContent).toContain("Uppdaterad plan.");
  });
});
