import { afterEach, expect, test, vi } from "vitest";

const locale = vi.hoisted(() => ({ current: "en" }));
vi.mock("$lib/paraglide/runtime", async (importOriginal) => ({
  ...(await importOriginal<typeof import("$lib/paraglide/runtime")>()),
  getLocale: () => locale.current
}));

import { formatBytes } from "./formatBytes";

afterEach(() => {
  locale.current = "en";
});

test("zero and negative sizes", () => {
  expect(formatBytes(0)).toEqual("0 B");
  expect(formatBytes(-1024)).toEqual("- B");
});

test("picks the largest base-1024 unit", () => {
  expect(formatBytes(1)).toEqual("1 B");
  expect(formatBytes(0.5)).toEqual("1 B");
  expect(formatBytes(1024)).toEqual("1 KB");
  expect(formatBytes(1536)).toEqual("2 KB");
  expect(formatBytes(1024 * 1024)).toEqual("1 MB");
  expect(formatBytes(1.5 * 1024 * 1024)).toEqual("2 MB");
  expect(formatBytes(1024 ** 3)).toEqual("1 GB");
  expect(formatBytes(1024 ** 5)).toEqual("1,024 TB");
});

test("uses fixed fraction digits in the UI language", () => {
  expect(formatBytes(1536, 1)).toEqual("1.5 KB");
  expect(formatBytes(1.5 * 1024 * 1024, 2)).toEqual("1.50 MB");
  locale.current = "sv";
  expect(formatBytes(1536, 1)).toEqual("1,5 KB");
});
