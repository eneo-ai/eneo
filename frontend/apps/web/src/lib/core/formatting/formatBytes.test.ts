import { expect, test } from "vitest";
import { formatBytes } from "./formatBytes";

test("Format 0 bytes", () => {
  expect(formatBytes(0)).toEqual("0 Bytes");
});

test("Format negative bytes", () => {
  expect(formatBytes(-1024)).toEqual("- Bytes");
});

test("Format bytes", () => {
  expect(formatBytes(1)).toEqual("1 Bytes");
});

test("Format kilobytes", () => {
  expect(formatBytes(1024)).toEqual("1 KB");
  expect(formatBytes(1536)).toEqual("2 KB");
});

test("Format megabytes", () => {
  expect(formatBytes(1024 * 1024)).toEqual("1 MB");
  expect(formatBytes(1.5 * 1024 * 1024)).toEqual("2 MB");
});

test("Format gigabytes", () => {
  expect(formatBytes(1024 * 1024 * 1024)).toEqual("1 GB");
});

test("Format with decimals", () => {
  expect(formatBytes(1536, 1)).toEqual("1.5 KB");
  expect(formatBytes(1.5 * 1024 * 1024, 2)).toEqual("1.50 MB");
});
