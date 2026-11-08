import { expect, test } from "bun:test";
import { cleanNumber, cleanNumbers } from "../src/precision";

test("a fraction loses the noise of double arithmetic, accumulated noise included", () => {
  expect(cleanNumber(1607240.97 - 1678000)).toBe(-70759.03);
  expect(cleanNumber(0.1 + 0.2)).toBe(0.3);
  expect(cleanNumber(-70759.0299999998)).toBe(-70759.03);
  expect(cleanNumber(-7833.3199999999779)).toBe(-7833.32);
  expect(cleanNumber(1678000.0000000002)).toBe(1678000);
  expect(cleanNumber(1607240.9700000002)).toBe(1607240.97);
});

test("a figure with real digits keeps at least thirteen of them", () => {
  expect(cleanNumber(0.00325)).toBe(0.00325);
  expect(cleanNumber(12345678901.23)).toBe(12345678901.23);
  expect(cleanNumber(0.1234567890123456)).toBe(0.12345678901235);
  expect(cleanNumber(1234567.890123)).toBe(1234567.890123);
  expect(cleanNumber(2.9103830456733704e-11)).toBe(2.9103830456734e-11);
});

test("integers, zero and non-finite values are returned as they are", () => {
  expect(cleanNumber(1607240)).toBe(1607240);
  expect(cleanNumber(0)).toBe(0);
  expect(cleanNumber(2 ** 53 + 2)).toBe(2 ** 53 + 2);
  expect(cleanNumber(1e21)).toBe(1e21);
  expect(cleanNumber(Number.NaN)).toBeNaN();
  expect(cleanNumber(Number.POSITIVE_INFINITY)).toBe(Number.POSITIVE_INFINITY);
});

test("a JSON value is cleaned in depth, with strings and nulls untouched", () => {
  expect(
    cleanNumbers({
      summa: 0.1 + 0.2,
      rader: [[1607240.97 - 1678000, "1607240.970"], { andel: 0.1 * 3, namn: null }],
    }),
  ).toEqual({
    summa: 0.3,
    rader: [[-70759.03, "1607240.970"], { andel: 0.3, namn: null }],
  });
  expect(cleanNumbers("0.30000000000000004")).toBe("0.30000000000000004");
});
