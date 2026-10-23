// Runs under `bun test`, like @eneo/whats-new: plain JSON imports work here
// and in the bundlers that consume this package.
import { expect, test } from "bun:test";
import { cases } from "../cases.json";

import { canCloseDollar, canFollowWithDollar, canOpenDollar, katexOptions } from "./index.js";

test("a dollar opens math only at a word boundary and before non-space", () => {
  expect(canOpenDollar(undefined, "x")).toBe(true);
  expect(canOpenDollar(" ", "x")).toBe(true);
  expect(canOpenDollar("(", "x")).toBe(true);
  expect(canOpenDollar("–", "1")).toBe(true);
  expect(canOpenDollar("a", "x")).toBe(false);
  expect(canOpenDollar("å", "x")).toBe(false);
  expect(canOpenDollar("5", "x")).toBe(false);
  expect(canOpenDollar("$", "x")).toBe(false);
  expect(canOpenDollar("𝑎".at(-1), "x")).toBe(false);
  expect(canOpenDollar(" ", " ")).toBe(false);
  expect(canOpenDollar(" ", "$")).toBe(false);
  expect(canOpenDollar(" ", undefined)).toBe(false);
});

test("a parser can ask about the character before a dollar on its own", () => {
  expect(canFollowWithDollar(undefined)).toBe(true);
  expect(canFollowWithDollar(" ")).toBe(true);
  expect(canFollowWithDollar("a")).toBe(false);
  expect(canFollowWithDollar("$")).toBe(false);
});

test("a dollar closes math only after non-space and before a non-word", () => {
  expect(canCloseDollar("x", undefined)).toBe(true);
  expect(canCloseDollar("x", ".")).toBe(true);
  expect(canCloseDollar("x", ")")).toBe(true);
  expect(canCloseDollar("\\", " ")).toBe(true);
  expect(canCloseDollar(" ", undefined)).toBe(false);
  expect(canCloseDollar(undefined, "x")).toBe(false);
  expect(canCloseDollar("x", "2")).toBe(false);
  expect(canCloseDollar("–", "1")).toBe(false);
  expect(canCloseDollar("x", "y")).toBe(false);
  expect(canCloseDollar("x", "$")).toBe(false);
  expect(canCloseDollar("x", "𝟚"[0])).toBe(false);
});

test("KaTeX never trusts input and bounds sizes", () => {
  const options = katexOptions(true);
  expect(options).toMatchObject({ displayMode: true, throwOnError: false, trust: false });
  expect(options.maxSize).toBeGreaterThan(0);
  expect(Number.isFinite(options.maxSize)).toBe(true);
  expect(options).not.toHaveProperty("macros");
  expect(katexOptions(false).displayMode).toBe(false);
});

test("every case is well formed and named once", () => {
  const names = new Set();
  for (const c of cases) {
    expect(typeof c.name).toBe("string");
    expect(names.has(c.name)).toBe(false);
    names.add(c.name);
    expect(typeof c.input).toBe("string");
    expect(Array.isArray(c.math)).toBe(true);
    for (const formula of c.math) {
      expect(typeof formula.display).toBe("boolean");
      expect(formula.tex.length).toBeGreaterThan(0);
    }
  }
});
