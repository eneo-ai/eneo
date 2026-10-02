import { expect, it } from "vitest";
import { conversationUploads } from "./conversationUploads";

const file = (id: string, name = "budget.xlsx") => ({
  id,
  name,
  mimetype: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  size: 120
});

it("keeps distinct uploads with identical names and deduplicates repeated references", () => {
  const first = file("first");
  const second = file("second");
  expect(conversationUploads([{ files: [first] }, { files: [first, second] }])).toEqual([
    first,
    second
  ]);
});
it("does not relist a generated document as an upload when later referenced", () => {
  const upload = file("source");
  const generated = file("result");
  expect(
    conversationUploads([{ files: [upload], generated_files: [generated] }, { files: [generated] }])
  ).toEqual([upload]);
});
it("only includes saved attachments from the current conversation", () => {
  expect(conversationUploads([{ files: [file("")] }, { files: null }, {}])).toEqual([]);
  expect(conversationUploads([])).toEqual([]);
});
