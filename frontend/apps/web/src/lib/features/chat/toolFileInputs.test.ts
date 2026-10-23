import { expect, it } from "vitest";
import { toolFileInputs, opensFilePanel } from "./toolFileInputs";
const source = {
  id: "12345678-1234-1234-1234-123456789abc",
  name: "original.xlsx",
  generated: false
};
const exported = {
  id: "23456789-1234-1234-1234-123456789abc",
  name: "result.csv",
  generated: true
};
const known = new Map([source, exported].map((file) => [file.id, file]));
const url = (id: string) =>
  `https://eneo.example/api/v1/files/${id}/original/download/?token=REDACTED`;
it("identifies the input independently of output filename and spoofed filename arguments", () => {
  expect(
    toolFileInputs(
      { file: { url: url(source.id), filename: "result.csv" }, export: { filename: "result.csv" } },
      known
    )
  ).toEqual([source]);
});
it("distinguishes generated inputs and deduplicates references across nested inputs", () => {
  expect(
    toolFileInputs(
      { files: [{ url: url(exported.id) }, { url: url(source.id) }, { url: url(exported.id) }] },
      known
    )
  ).toEqual([exported, source]);
});
it("does not guess from names or expose URLs for unknown files", () => {
  expect(
    toolFileInputs(
      { file: { filename: "original.xlsx", url: url("33456789-1234-1234-1234-123456789abc") } },
      known
    )
  ).toEqual([]);
});
it("automatically previews file creation, not analysis exports or charts", () => {
  expect(opensFilePanel({ purpose: "file_creation" })).toBe(true);
  expect(opensFilePanel({ purpose: "file_analysis" })).toBe(false);
  expect(opensFilePanel({ purpose: "chart_generation" })).toBe(false);
  expect(opensFilePanel(undefined)).toBe(false);
});

it("identifies stable handles without exposing identifiers as labels", () => {
  expect(
    toolFileInputs(
      {
        images: [{ url: `eneo-file:${exported.id.replaceAll("-", "")}` }],
        file: { url: `eneo-file:${source.id.replaceAll("-", "")}` }
      },
      known
    )
  ).toEqual([exported, source]);
});
