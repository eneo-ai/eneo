import { describe, expect, it } from "vitest";
import type { EneoUIMessage } from "@/lib/chat/types";
import { addGeneratedFile, messageGeneratedFiles } from "./message-tool-calls";

const md = "text/markdown";
const plan1 = {
  id: "11111111-1111-1111-1111-111111111111",
  name: "Plan.md",
  mimetype: md,
  size: 10
};
const plan2 = {
  id: "22222222-2222-2222-2222-222222222222",
  name: "Plan.md",
  mimetype: md,
  size: 12
};

const question: EneoUIMessage = { id: "q", role: "user", parts: [{ type: "text", text: "Hej" }] };
const answer = (id: string, files: (typeof plan1)[]): EneoUIMessage => ({
  id,
  role: "assistant",
  parts: [{ type: "text", text: "Här" }],
  metadata: { generatedFiles: files }
});

describe("a version the reader saved", () => {
  it("joins the answer that holds the version it was edited from", () => {
    const messages = [question, answer("a1", [plan1]), question, answer("a2", [])];
    const saved = { ...plan2, revises_file_id: plan1.id };
    const updated = addGeneratedFile(messages, saved);
    expect(messageGeneratedFiles(updated[1]!).map((file) => file.id)).toEqual([plan1.id, plan2.id]);
    expect(messageGeneratedFiles(updated[3]!)).toEqual([]);
    // The other messages are the same objects.
    expect(updated[0]).toBe(messages[0]);
    expect(updated[3]).toBe(messages[3]);
  });

  it("joins the last answer when no answer holds the version edited from", () => {
    const messages = [question, answer("a1", [])];
    const updated = addGeneratedFile(messages, { ...plan2, revises_file_id: null });
    expect(messageGeneratedFiles(updated[1]!).map((file) => file.id)).toEqual([plan2.id]);
  });

  it("changes nothing when the answer has it already", () => {
    const messages = [question, answer("a1", [plan1, plan2])];
    expect(addGeneratedFile(messages, { ...plan2, revises_file_id: plan1.id })).toBe(messages);
  });
});
