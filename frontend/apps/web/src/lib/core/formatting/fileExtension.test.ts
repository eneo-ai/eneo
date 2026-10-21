import { expect, it } from "vitest";
import { fileExtension } from "./fileExtension";

it("upper-cases the last extension", () => {
  expect(fileExtension("Report.pdf")).toBe("PDF");
  expect(fileExtension("archive.tar.gz")).toBe("GZ");
});

it("gives nothing for a name without an extension", () => {
  expect(fileExtension("README")).toBe("");
  expect(fileExtension(".env")).toBe("");
  expect(fileExtension("notes.")).toBe("");
});
