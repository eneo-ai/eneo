import { describe, expect, it } from "vitest";
import { planChatAttachmentUploads } from "./chat-attachment-plan";

const formats = [
  { mimetype: "application/pdf", size: 1_000 },
  { mimetype: "image/png", size: 500 }
];

describe("planChatAttachmentUploads", () => {
  it("accepts files within type, size, and count limits", () => {
    const plan = planChatAttachmentUploads(
      [
        { name: "a.pdf", size: 800, type: "application/pdf" },
        { name: "b.png", size: 300, type: "image/png" }
      ],
      0,
      formats,
      2
    );

    expect(plan.accepted.map((file) => file.name)).toEqual(["a.pdf", "b.png"]);
    expect(plan.rejected).toEqual([]);
  });

  it("does not let unsupported or oversized files consume max-file slots", () => {
    const plan = planChatAttachmentUploads(
      [
        { name: "unsupported.txt", size: 10, type: "text/plain" },
        { name: "too-large.png", size: 700, type: "image/png" },
        { name: "accepted.pdf", size: 900, type: "application/pdf" }
      ],
      0,
      formats,
      1
    );

    expect(plan.accepted.map((file) => file.name)).toEqual(["accepted.pdf"]);
    expect(plan.rejected.map((rejection) => [rejection.file.name, rejection.reason])).toEqual([
      ["unsupported.txt", "unsupported-type"],
      ["too-large.png", "too-large"]
    ]);
  });

  it("rejects files after the configured max count", () => {
    const plan = planChatAttachmentUploads(
      [
        { name: "b.pdf", size: 200, type: "application/pdf" },
        { name: "c.pdf", size: 200, type: "application/pdf" }
      ],
      1,
      formats,
      2
    );

    expect(plan.accepted.map((file) => file.name)).toEqual(["b.pdf"]);
    expect(plan.rejected).toEqual([
      { file: { name: "c.pdf", size: 200, type: "application/pdf" }, reason: "max-files", limit: 2 }
    ]);
  });

  it("treats zero max files as attachments disabled", () => {
    const plan = planChatAttachmentUploads(
      [{ name: "a.pdf", size: 200, type: "application/pdf" }],
      0,
      formats,
      0
    );

    expect(plan.accepted).toEqual([]);
    expect(plan.rejected[0]?.reason).toBe("max-files");
  });
});
