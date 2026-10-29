import { expect, it } from "vitest";
import { parseRetentionDays, RETENTION_MAX_DAYS } from "./retention-days";

it("accepts whole days within the backend's 1-2555 bounds", () => {
  expect(RETENTION_MAX_DAYS).toBe(2555);
  expect(parseRetentionDays("1")).toBe(1);
  expect(parseRetentionDays("2555")).toBe(2555);
});

it("reads an empty field as inheriting the policy above", () => {
  expect(parseRetentionDays("")).toBeNull();
});

it("rejects out-of-range and malformed values", () => {
  for (const value of ["0", "2556", "1e3", " 5", "5 ", "abc", "-3", "1.5"]) {
    expect(parseRetentionDays(value), value).toBeUndefined();
  }
});
