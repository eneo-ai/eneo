import { expect, it } from "vitest";
import type { EneoUIMessage } from "@/lib/chat/types";
import { conversationUploadGroups, conversationUploads } from "./panel-contents";

it("groups canonical uploads by their first explicit question, leaving session-only files unassigned", () => {
  const file = (id: string) => ({ id, name: `${id}.pdf`, mimetype: "application/pdf", size: 10 });
  const first = file("first"),
    second = file("second"),
    unknown = file("unknown"),
    generated = file("generated");
  const messages: EneoUIMessage[] = [
    { id: "q1", role: "user", parts: [{ type: "text", text: "No uploads" }] },
    {
      id: "q2",
      role: "user",
      parts: [{ type: "text", text: "First file" }],
      metadata: { files: [first] }
    },
    {
      id: "q3",
      role: "user",
      parts: [{ type: "text", text: "Reuse and add" }],
      metadata: { files: [first, second, generated] }
    },
    {
      id: "a3",
      role: "assistant",
      metadata: { generatedFiles: [generated] },
      parts: [
        {
          type: "data-session",
          data: {
            session_id: "s1",
            completion_model: null,
            files: [{ ...first, name: "Canonical.pdf" }, unknown],
            web_search_references: []
          }
        }
      ]
    }
  ];
  const uploads = conversationUploads(messages);
  const groups = conversationUploadGroups(messages, uploads);
  expect(
    groups.map((group) => [group.key, group.ordinal, group.files.map((file) => file.id)])
  ).toEqual([
    ["q2", 2, ["first"]],
    ["q3", 3, ["second"]],
    ["unassigned", null, ["unknown"]]
  ]);
  expect(groups[0]!.files[0]).toBe(uploads.find((file) => file.id === "first"));
  expect(groups[0]!.files[0]!.name).toBe("Canonical.pdf");
});
