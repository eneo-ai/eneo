import { describe, expect, it } from "vitest";
import {
  conversationDocuments,
  editedPassage,
  isDocument,
  revisedDocumentName,
  revisedFileId
} from "./document-versions";

const md = "text/markdown";
const docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
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
const planDocx = {
  id: "33333333-3333-3333-3333-333333333333",
  name: "Plan.docx",
  mimetype: docx,
  size: 90
};
const image = {
  id: "44444444-4444-4444-4444-444444444444",
  name: "chart.png",
  mimetype: "image/png",
  size: 5
};

const revises = (file: { id: string; name: string }) => ({
  revises: { url: `eneo-file:${file.id.replace(/-/g, "")}`, filename: file.name }
});

describe("conversation documents", () => {
  it("lists a revised document once, with its versions in order", () => {
    const { documents, latestOf, versionsOf } = conversationDocuments([
      { files: [plan1], calls: [{ toolCallId: "c1", input: {}, generatedFileIds: [plan1.id] }] },
      {
        files: [plan2],
        calls: [{ toolCallId: "c2", input: revises(plan1), generatedFileIds: [plan2.id] }]
      }
    ]);
    expect(documents).toEqual([{ latest: plan2, versions: [plan1, plan2] }]);
    expect(latestOf(plan1.id)).toEqual(plan2);
    expect(versionsOf(plan2.id)).toEqual([plan1, plan2]);
  });

  it("keeps the same content in another format as a document of its own", () => {
    const { documents } = conversationDocuments([
      { files: [plan1], calls: [] },
      {
        files: [planDocx],
        calls: [{ toolCallId: "c2", input: revises(plan1), generatedFileIds: [planDocx.id] }]
      }
    ]);
    expect(documents.map((document) => document.latest)).toEqual([plan1, planDocx]);
  });

  it("tells documents from images and reads the revised file from a signed link", () => {
    expect(isDocument(image)).toBe(false);
    expect(isDocument(plan1)).toBe(true);
    expect(isDocument({ id: "", mimetype: md })).toBe(false);
    expect(
      revisedFileId({
        revises: { url: `https://eneo.test/api/v1/files/${plan1.id}/original/download/?token=x` }
      })
    ).toBe(plan1.id);
    expect(revisedFileId(revises(plan1))).toBe(plan1.id);
    expect(revisedFileId({})).toBeNull();
  });
});

describe("an edited document", () => {
  it("is named by the document it changes", () => {
    expect(revisedDocumentName(revises(plan1))).toBe("Plan");
    expect(revisedDocumentName({})).toBeNull();
  });

  it("points out the first replacement as it reads once rendered", () => {
    expect(
      editedPassage({ edits: [{ find: "x", replace: "## **Pilotgruppen** startar [först](a)" }] })
    ).toBe("Pilotgruppen startar först");
  });

  it("points out nothing for a removal, a table row or a call that is not an edit", () => {
    expect(editedPassage({ edits: [{ find: "x", replace: "" }] })).toBeNull();
    expect(editedPassage({ edits: [{ find: "x", replace: "| a | b |" }] })).toBeNull();
    expect(editedPassage({ content: "text" })).toBeNull();
  });
});
