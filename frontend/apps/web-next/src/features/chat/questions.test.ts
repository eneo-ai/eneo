import { describe, expect, it } from "vitest";
import type { EneoUIMessage } from "@/lib/chat/types";
import {
  questionAnswer,
  questionAnsweredBy,
  questionOf,
  questionToAnswer,
  type AskedQuestion
} from "./questions";
import { messageToolCalls } from "./side-panel/message-tool-calls";

type Part = EneoUIMessage["parts"][number];

const content = {
  question: "Vem ska läsa PM:et?",
  header: "Mottagare",
  options: [
    { label: "Nämnden", description: "Beslutsunderlag." },
    { label: "Ledningen", description: null }
  ],
  multi_select: false
};

function askCall(
  overrides: Partial<{
    status: "succeeded" | "failed";
    structured: Record<string, unknown> | null;
    serverName: string;
    isInternal: boolean;
  }> = {}
): Part {
  const status = overrides.status ?? "succeeded";
  return {
    type: "dynamic-tool",
    toolName: "ask_user",
    toolCallId: "ask-1",
    state: status === "succeeded" ? "output-available" : "output-error",
    input: content,
    output: { status },
    errorText: status === "failed" ? "failed" : undefined,
    providerMetadata: {
      eneo: {
        server_name: overrides.serverName ?? "questions",
        is_internal: overrides.isInternal ?? true,
        result_status: status,
        structured_content: "structured" in overrides ? overrides.structured : content
      }
    }
  } as Part;
}

/** The one tool call of an answer made of `parts`. */
function callOf(...parts: Part[]) {
  const [call] = messageToolCalls({ id: "a", role: "assistant", parts });
  if (!call) throw new Error("no tool call");
  return call;
}

const answerWithQuestion: EneoUIMessage = {
  id: "a1",
  role: "assistant",
  parts: [{ type: "text", text: "En sak först.", state: "done" }, askCall()]
};
const user = (id: string, text: string): EneoUIMessage => ({
  id,
  role: "user",
  parts: [{ type: "text", text }]
});

describe("questionOf", () => {
  it("reads the question off the call's structured content", () => {
    expect(questionOf(callOf(...answerWithQuestion.parts))).toEqual({
      question: "Vem ska läsa PM:et?",
      header: "Mottagare",
      options: [
        { label: "Nämnden", description: "Beslutsunderlag." },
        { label: "Ledningen", description: null }
      ],
      multiSelect: false
    });
  });

  it("is null for a refused question, another server's ask_user, or too few options", () => {
    const of = (part: Part) => questionOf(callOf(part));
    expect(of(askCall({ status: "failed", structured: null }))).toBeNull();
    expect(of(askCall({ serverName: "questions", isInternal: false }))).toBeNull();
    expect(of(askCall({ structured: { ...content, options: [content.options[0]] } }))).toBeNull();
    expect(of(askCall({ structured: { ...content, question: "" } }))).toBeNull();
  });
});

describe("questionToAnswer", () => {
  it("is the question the last answer ends with, once the answer is complete", () => {
    const messages = [user("q1", "Skriv en PM"), answerWithQuestion];
    expect(questionToAnswer(messages, false)).toMatchObject({
      messageId: "a1",
      toolCallId: "ask-1",
      question: "Vem ska läsa PM:et?"
    });
    expect(questionToAnswer(messages, true)).toBeNull();
  });

  it("is answered by any message sent after it", () => {
    const messages = [user("q1", "Skriv en PM"), answerWithQuestion, user("q2", "Nämnden")];
    expect(questionToAnswer(messages, false)).toBeNull();
    expect(questionAnsweredBy(messages, 2)?.question).toBe("Vem ska läsa PM:et?");
    expect(questionAnsweredBy(messages, 0)).toBeNull();
  });
});

describe("questionAnswer", () => {
  const question: AskedQuestion = {
    question: "Vilka delar?",
    header: null,
    options: [
      { label: "Riktlinjer", description: null },
      { label: "Ärendebrev", description: null },
      { label: "Mallar", description: null }
    ],
    multiSelect: true
  };

  it("names the picks in the question's order, then the person's own words", () => {
    expect(questionAnswer(question, ["Mallar", "Riktlinjer"], "")).toBe("Riktlinjer, Mallar");
    expect(questionAnswer(question, ["Mallar"], " Bara de nya. ")).toBe("Mallar. Bara de nya.");
    expect(questionAnswer(question, [], "Inget av dem")).toBe("Inget av dem");
    expect(questionAnswer(question, [], "  ")).toBe("");
  });
});
