import { expect, test } from "bun:test";
import { isNumeric, numberFormatter } from "../../src/views/kit/numbers";

/** The group separator Swedish Intl writes. */
const NBSP = "\u00a0";
/** The minus sign Swedish Intl writes; display only, copy and export keep the raw value. */
const MINUS = "\u2212";

test("numbers are shown in the reader's locale, four-digit numbers ungrouped", () => {
  const sv = numberFormatter("sv");
  expect(sv(120924.67)).toBe(`120${NBSP}924,67`);
  expect(sv(2024)).toBe("2024");
  expect(sv(12345)).toBe(`12${NBSP}345`);
  expect(sv(0.00325)).toBe("0,00325");
  expect(sv(-1234.5)).toBe(`${MINUS}1234,5`);
  expect(sv(-12345.5)).toBe(`${MINUS}12${NBSP}345,5`);
  expect(numberFormatter("en")(120924.67)).toBe("120,924.67");
  expect(numberFormatter(undefined)(1000000)).toBe(`1${NBSP}000${NBSP}000`);
});

test("a decimal string is shown as the number it is, keeping the script's decimals", () => {
  const sv = numberFormatter("sv");
  expect(sv("120924.67")).toBe(`120${NBSP}924,67`);
  expect(sv("1007.70")).toBe("1007,70");
  expect(sv("10077.70")).toBe(`10${NBSP}077,70`);
  expect(sv("0.00325")).toBe("0,00325");
  expect(sv("-0.50")).toBe(`${MINUS}0,50`);
  expect(numberFormatter("en")("120924.67")).toBe("120,924.67");
});

test("strings a double cannot carry, digit strings and other text are left as they are", () => {
  const sv = numberFormatter("sv");
  expect(sv("1234567890.1234567")).toBe("1234567890.1234567");
  expect(sv("0.1234567890123456")).toBe("0.1234567890123456");
  expect(sv("19850101")).toBe("19850101");
  expect(sv("12345678901234567890")).toBe("12345678901234567890");
  expect(sv("1 234,50")).toBe("1 234,50");
  expect(sv("abc")).toBe("abc");
  expect(sv("")).toBe("");
});

test("a column aligns on numbers and numeric strings", () => {
  expect(isNumeric(7)).toBe(true);
  expect(isNumeric("1007.71")).toBe(true);
  expect(isNumeric("12345678901234567890")).toBe(true);
  expect(isNumeric("1 234,50")).toBe(false);
  expect(isNumeric("kr")).toBe(false);
  expect(isNumeric(null)).toBe(false);
});
