import { describe, expect, it } from "vitest";
import {
  conversationDocuments,
  editedPassage,
  isDocument,
  revisedDocumentName,
  revisedFileId
} from "./documentVersions";

const ID = {
  plan1: "11111111-1111-1111-1111-111111111111",
  plan2: "22222222-2222-2222-2222-222222222222",
  plan3: "33333333-3333-3333-3333-333333333333",
  word: "44444444-4444-4444-4444-444444444444",
  chart: "55555555-5555-5555-5555-555555555555"
};

const file = (id: string, name: string, mimetype = "text/markdown") => ({
  id,
  name,
  mimetype,
  size: 10
});
// History keeps the link with its token removed; the path still names the file.
const link = (id: string) =>
  `https://eneo.test/api/v1/files/${id}/original/download/?token=REDACTED`;
const recorded = (call: { generated_file_ids?: string[] | null }) => call.generated_file_ids ?? [];

describe("conversation documents", () => {
  const messages = [
    {
      generated_files: [file(ID.plan1, "Plan.md")],
      tool_calls: [{ tool_call_id: "a", arguments: {}, generated_file_ids: [ID.plan1] }]
    },
    {
      generated_files: [file(ID.plan2, "Plan.md"), file(ID.chart, "chart.png", "image/png")],
      tool_calls: [
        {
          tool_call_id: "b",
          arguments: { revises: { url: link(ID.plan1), filename: "Plan.md" } },
          generated_file_ids: [ID.plan2]
        }
      ]
    },
    {
      generated_files: [file(ID.plan3, "Plan.md")],
      tool_calls: [
        {
          tool_call_id: "c",
          arguments: { revises: { url: link(ID.plan2), filename: "Plan.md" } },
          generated_file_ids: [ID.plan3]
        }
      ]
    }
  ];

  it("lists a revised document once, with its versions in order", () => {
    const { documents, latestOf, versionsOf } = conversationDocuments(messages, recorded);

    expect(documents).toHaveLength(1);
    expect(documents[0].latest.id).toBe(ID.plan3);
    expect(documents[0].versions.map((version) => version.id)).toEqual([
      ID.plan1,
      ID.plan2,
      ID.plan3
    ]);
    expect(latestOf(ID.plan1)?.id).toBe(ID.plan3);
    expect(latestOf(ID.plan3)?.id).toBe(ID.plan3);
    // Any version leads to all of them, oldest first.
    expect(versionsOf(ID.plan2).map((file) => file.id)).toEqual([ID.plan1, ID.plan2, ID.plan3]);
    expect(versionsOf(ID.chart)).toEqual([]);
  });

  it("keeps the same content in another format as a document of its own", () => {
    const { documents } = conversationDocuments(
      [
        ...messages,
        {
          generated_files: [file(ID.word, "Plan.docx", "application/msword")],
          tool_calls: [
            {
              tool_call_id: "d",
              arguments: { revises: { url: link(ID.plan3), filename: "Plan.md" } },
              generated_file_ids: [ID.word]
            }
          ]
        }
      ],
      recorded
    );

    expect(documents.map((document) => document.latest.id)).toEqual([ID.plan3, ID.word]);
  });

  it("links the files of a streamed answer through the caller's lookup", () => {
    const live = new Map([["b", [ID.plan2]]]);
    const { documents } = conversationDocuments(
      [
        messages[0],
        {
          generated_files: [file(ID.plan2, "Plan.md")],
          mcp_tool_calls: [{ tool_call_id: "b", arguments: { revises: { url: link(ID.plan1) } } }]
        }
      ],
      (call) => call.generated_file_ids ?? live.get(call.tool_call_id ?? "") ?? []
    );

    expect(documents).toHaveLength(1);
    expect(documents[0].latest.id).toBe(ID.plan2);
  });

  it("tells documents from images and reads the revised file from a signed link", () => {
    expect(isDocument(file(ID.chart, "chart.png", "image/png"))).toBe(false);
    expect(isDocument(file("", "", ""))).toBe(false);
    expect(revisedFileId({ revises: { url: link(ID.plan1) } })).toBe(ID.plan1);
    expect(revisedFileId({ revises: { url: "https://example.com/plan.md" } })).toBeNull();
    expect(revisedFileId({})).toBeNull();
  });
});

describe("an edited document", () => {
  it("is named by the document it changes", () => {
    expect(revisedDocumentName({ revises: { url: link(ID.plan1), filename: "Plan 2.0.md" } })).toBe(
      "Plan 2.0"
    );
    expect(revisedDocumentName({ title: "Plan" })).toBeNull();
  });

  it("points out the first replacement as it reads once rendered", () => {
    expect(
      editedPassage({
        edits: [
          { find: "a", replace: "" },
          { find: "b", replace: "\n- [ ] **Pilotgruppen** startar i [juni](https://x.test)\nmer" }
        ]
      })
    ).toBe("Pilotgruppen startar i juni");
  });

  it("points out nothing for a removal, a table row or a call that is not an edit", () => {
    expect(editedPassage({ edits: [{ find: "a", replace: "" }] })).toBeNull();
    expect(editedPassage({ edits: [{ find: "a", replace: "| Skola | 12 |" }] })).toBeNull();
    expect(editedPassage({ content: "# Plan" })).toBeNull();
  });
});

it("groups revisions by stable file handle even when the new filename changes", () => {
  const messages = [
    { generated_files: [file(ID.plan1, "First.md")] },
    {
      generated_files: [file(ID.plan2, "Renamed.md")],
      tool_calls: [
        {
          arguments: { revises: { url: `eneo-file:${ID.plan1.replaceAll("-", "")}` } },
          generated_file_ids: [ID.plan2]
        }
      ]
    }
  ];
  const grouped = conversationDocuments(messages, recorded);
  expect(grouped.documents).toHaveLength(1);
  expect(grouped.documents[0].versions.map((version) => version.id)).toEqual([ID.plan1, ID.plan2]);
});
