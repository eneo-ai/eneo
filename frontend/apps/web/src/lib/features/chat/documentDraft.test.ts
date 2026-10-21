import { describe, expect, it } from "vitest";
import { documentDraft } from "./documentDraft";
import { readPartialArguments } from "./partialToolArguments";

const call = { tool_call_id: "one", purpose: "file_creation", result_status: "pending" };
describe("file creation drafts", () => {
  it("opens before any content arrives", () => {
    expect(documentDraft(call, {}, false)).toMatchObject({ callId: "one", text: "" });
  });
  it.each(["md", "docx", "pdf"])("shows real streaming text for %s", (format) => {
    const args = readPartialArguments(`{"format":"${format}","title":"Report","content":"First`);
    expect(documentDraft(call, args, false)?.text).toBe("# Report\n\nFirst");
  });
  it("shows nested streamed sheet rows without exposing source URLs", () => {
    const args = readPartialArguments(
      '{"title":"Budget","sheets":[{"name":"January","columns":["Budget"],"rows":[[123], [456'
    );
    expect(documentDraft(call, args, false)?.sheets?.[0]).toMatchObject({
      name: "January",
      columns: ["Budget"],
      rows: [["123"], []]
    });
    const source = documentDraft(
      call,
      { sheets: [{ name: "Data", source: { url: "secret" } }] },
      false
    );
    expect(source?.sheets?.[0].fromSource).toBe(true);
    expect(JSON.stringify(source)).not.toContain("secret");
  });
  it("bounds previews and does not invent body rows from a source", () => {
    const draft = documentDraft(
      call,
      { sheets: [{ columns: ["x"], rows: Array.from({ length: 200 }, () => [1]) }] },
      false
    );
    expect(draft?.sheets?.[0].rows).toHaveLength(100);
    expect(draft?.sheets?.[0].truncated).toBe(true);
  });
  it("never renders document image markers as browser URLs", () => {
    expect(documentDraft(call, { content: "![Monthly costs](image:chart1)" }, false)?.text).toBe(
      "Monthly costs"
    );
  });
  it.each(["failed", "denied", "timeout_denied", "succeeded", "completed"])(
    "does not keep a %s call writing",
    (result_status) => {
      expect(documentDraft({ ...call, result_status }, {}, false)).toBeNull();
    }
  );
  it("stops when the file arrives or permission is denied", () => {
    expect(documentDraft(call, {}, true)).toBeNull();
    expect(documentDraft({ ...call, approved: false }, {}, false)).toBeNull();
  });
});
