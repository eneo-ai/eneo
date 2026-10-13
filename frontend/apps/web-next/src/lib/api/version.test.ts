import { expect, it } from "vitest";
import { backendVersionFrom } from "./version";

it("reads the version from the backend's answer", () => {
  expect(backendVersionFrom({ version: "2.3.0" })).toBe("2.3.0");
});

it("is empty when the answer has no version", () => {
  expect(backendVersionFrom({})).toBe("");
  expect(backendVersionFrom({ version: 2 })).toBe("");
  expect(backendVersionFrom(null)).toBe("");
});
