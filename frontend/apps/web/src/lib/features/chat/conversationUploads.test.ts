import { expect, it } from "vitest";
import {
  conversationUploadGroups,
  conversationUploads,
  uploadGroupKey
} from "./conversationUploads";

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

it("groups uploads by the question that brought them, numbered by its place", () => {
  const first = file("first");
  const second = file("second");
  const third = file("third");
  expect(
    conversationUploadGroups([
      { id: "q1", files: [first] },
      { id: "q2", files: [] },
      { id: "q3", files: [first, second, third] }
    ])
  ).toEqual([
    { key: "q1", ordinal: 1, files: [first] },
    { key: "q3", ordinal: 3, files: [second, third] }
  ]);
});
it("names a group after the message, or its first file until the message has an id", () => {
  expect(uploadGroupKey({ id: "q1", files: [file("a")] })).toBe("q1");
  expect(uploadGroupKey({ id: null, files: [file(""), file("a")] })).toBe("file:a");
  expect(uploadGroupKey({ files: [] })).toBeNull();
});
