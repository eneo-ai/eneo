import { describe, expect, it } from "vitest";
import { citedTextDocumentReferences, redundantInrefIds } from "./mcpReferenceDocs";

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

describe("redundantInrefIds", () => {
  const DOC = "eneo://info-blob/a858607e-d7f7-424d-9c98-4706bd2c11a0";
  const OTHER = "eneo://info-blob/b0000000-d7f7-424d-9c98-4706bd2c11a0";

  const passage = (id: string, uri: string, chunk: number) =>
    ref(id, { uri: `${uri}#chunk-${chunk}` });

  const first = passage("11111111-aaaa-4aaa-8aaa-aaaaaaaaaaaa", DOC, 1);
  const second = passage("22222222-bbbb-4bbb-8bbb-bbbbbbbbbbbb", DOC, 10);
  const elsewhere = passage("33333333-cccc-4ccc-8ccc-cccccccccccc", OTHER, 2);

  const shortId = (id: string) => id.slice(0, 8);

  it("suppresses a neighbouring citation of the same document", () => {
    const result = redundantInrefIds(
      [first, second],
      `Server-side API:er.${inref(first.id)} ${inref(second.id)}`
    );

    expect([...result]).toEqual([shortId(second.id)]);
  });

  it("keeps neighbouring citations of different documents", () => {
    const result = redundantInrefIds(
      [first, elsewhere],
      `Two sources.${inref(first.id)} ${inref(elsewhere.id)}`
    );

    expect([...result]).toEqual([]);
  });

  it("keeps a later citation of the same document separated by prose", () => {
    const result = redundantInrefIds(
      [first, second],
      `One claim.${inref(first.id)} A separate claim.${inref(second.id)}`
    );

    expect([...result]).toEqual([]);
  });

  it("keeps a citation that also stands alone elsewhere in the answer", () => {
    const result = redundantInrefIds(
      [first, second],
      `Together.${inref(first.id)} ${inref(second.id)} Alone.${inref(second.id)}`
    );

    expect([...result]).toEqual([]);
  });

  it("collapses a run of three passages from one document to the first", () => {
    const third = passage("44444444-dddd-4ddd-8ddd-dddddddddddd", DOC, 4);
    const result = redundantInrefIds(
      [first, second, third],
      `Everything.${inref(first.id)} ${inref(second.id)} ${inref(third.id)}`
    );

    expect([...result].sort()).toEqual([shortId(second.id), shortId(third.id)].sort());
  });

  it("never suppresses a citation id that matches no reference", () => {
    const result = redundantInrefIds([first], `Claim.${inref(first.id)} <inref id="deadbeef"/>`);

    expect([...result]).toEqual([]);
  });

  it("reports nothing for an answer without citations", () => {
    expect([...redundantInrefIds([first], "Plain answer.")]).toEqual([]);
  });
});
