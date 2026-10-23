import { describe, expect, it } from "vitest";
import { isSameFile, matchesUpload, planChatAttachmentUploads } from "./chat-attachment-plan";

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
      [],
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
      [],
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
      [{ name: "a.pdf", size: 100, type: "application/pdf" }],
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
      [],
      formats,
      0
    );

    expect(plan.accepted).toEqual([]);
    expect(plan.rejected[0]?.reason).toBe("max-files");
  });

  it("skips a file the composer already holds without taking a slot", () => {
    const held = { name: "a.pdf", size: 200, type: "application/pdf", lastModified: 1 };
    const plan = planChatAttachmentUploads(
      [
        { ...held },
        { ...held, lastModified: 2 },
        { name: "b.pdf", size: 200, type: "application/pdf", lastModified: 3 }
      ],
      [held],
      formats,
      3
    );

    expect(plan.rejected).toEqual([{ file: held, reason: "duplicate" }]);
    expect(plan.accepted.map((file) => file.name)).toEqual(["a.pdf", "b.pdf"]);
  });

  it("attaches a file the server already has instead of uploading it again", () => {
    const uploaded = { id: "f1", name: "a.pdf", mimetype: "application/pdf", size: 200 };
    const plan = planChatAttachmentUploads(
      [
        { name: "a.pdf", size: 200, type: "application/pdf" },
        { name: "b.pdf", size: 200, type: "application/pdf" }
      ],
      [],
      formats,
      2,
      (file) => (matchesUpload(file, uploaded) ? uploaded : undefined)
    );

    expect(plan.reused).toEqual([
      { file: { name: "a.pdf", size: 200, type: "application/pdf" }, uploaded }
    ]);
    expect(plan.accepted.map((file) => file.name)).toEqual(["b.pdf"]);
  });
});

describe("isSameFile", () => {
  it("compares name, size, type and modification time", () => {
    const file = { name: "a.pdf", size: 1, type: "application/pdf", lastModified: 10 };
    expect(isSameFile(file, { ...file })).toBe(true);
    expect(isSameFile(file, { ...file, lastModified: 11 })).toBe(false);
    expect(isSameFile(file, { ...file, size: 2 })).toBe(false);
  });
});

describe("matchesUpload", () => {
  const uploaded = {
    id: "f1",
    name: "report.docx",
    mimetype: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    size: 900,
    original_size: 40_000
  };

  it("matches on name, type and the stored original's size", () => {
    const file = { name: "report.docx", size: 40_000, type: uploaded.mimetype };
    expect(matchesUpload(file, uploaded)).toBe(true);
    expect(matchesUpload({ ...file, size: 900 }, uploaded)).toBe(false);
    expect(matchesUpload({ ...file, name: "other.docx" }, uploaded)).toBe(false);
  });

  it("falls back to the file's size when no original size is known", () => {
    const text = { id: "f2", name: "notes.txt", mimetype: "text/plain", size: 12 };
    expect(matchesUpload({ name: "notes.txt", size: 12, type: "text/plain" }, text)).toBe(true);
    expect(
      matchesUpload({ name: "notes.txt", size: 12, type: "text/plain;charset=utf-8" }, text)
    ).toBe(true);
  });
});
