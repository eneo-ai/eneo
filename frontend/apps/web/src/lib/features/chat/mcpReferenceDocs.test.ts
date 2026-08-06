import { describe, expect, it } from "vitest";
import { citedTextDocumentReferences } from "./mcpReferenceDocs";

function ref(
  id: string,
  overrides: Partial<Parameters<typeof citedTextDocumentReferences>[0][number]> = {}
) {
  return {
    id,
    uri: `eneo://info-blob/${id}#chunk-0`,
    content: "passage",
    mime_type: "text/plain",
    meta: {},
    ...overrides
  };
}

const inref = (id: string) => `<inref id="${id.slice(0, 8)}"/>`;

describe("citedTextDocumentReferences", () => {
  it("keeps only references cited inline in the answer", () => {
    const cited = ref("11111111-aaaa-4aaa-8aaa-aaaaaaaaaaaa");
    const uncited = ref("22222222-bbbb-4bbb-8bbb-bbbbbbbbbbbb");

    const result = citedTextDocumentReferences(
      [uncited, cited],
      `A fact.${inref(cited.id)} And an uncited claim.`
    );

    expect(result).toEqual([cited]);
  });

  it("orders references by first citation appearance", () => {
    const first = ref("11111111-aaaa-4aaa-8aaa-aaaaaaaaaaaa");
    const second = ref("22222222-bbbb-4bbb-8bbb-bbbbbbbbbbbb");

    const result = citedTextDocumentReferences(
      [first, second],
      `B first.${inref(second.id)} Then A.${inref(first.id)}`
    );

    expect(result).toEqual([second, first]);
  });

  it("returns one entry per reference regardless of repeated citations", () => {
    const cited = ref("11111111-aaaa-4aaa-8aaa-aaaaaaaaaaaa");

    const result = citedTextDocumentReferences(
      [cited],
      `Twice.${inref(cited.id)} Again.${inref(cited.id)}`
    );

    expect(result).toEqual([cited]);
  });

  it("ignores citation ids that match no reference", () => {
    const result = citedTextDocumentReferences(
      [ref("11111111-aaaa-4aaa-8aaa-aaaaaaaaaaaa")],
      'Cites nothing real.<inref id="deadbeef"/>'
    );

    expect(result).toEqual([]);
  });

  it("never returns image references even when their id is cited", () => {
    const image = ref("33333333-cccc-4ccc-8ccc-cccccccccccc", {
      uri: "https://example.test/chart.png",
      mime_type: "image/png",
      content: null
    });

    const result = citedTextDocumentReferences([image], `See chart.${inref(image.id)}`);

    expect(result).toEqual([]);
  });

  it("returns nothing for an answer without citations", () => {
    expect(
      citedTextDocumentReferences([ref("11111111-aaaa-4aaa-8aaa-aaaaaaaaaaaa")], "Plain answer.")
    ).toEqual([]);
  });
});
