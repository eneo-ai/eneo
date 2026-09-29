import { expect, test } from "vitest";
import { escapeHtml } from "./escapeHtml";

test("escapes markup so it is shown as text", () => {
  expect(escapeHtml('<img src=x onerror="alert(1)">')).toBe('&lt;img src=x onerror="alert(1)"&gt;');
});

test("escapes ampersands before the other entities", () => {
  expect(escapeHtml("a &lt; b & c")).toBe("a &amp;lt; b &amp; c");
});

test("leaves plain text unchanged", () => {
  expect(escapeHtml('{"name": "Budget 2026"}')).toBe('{"name": "Budget 2026"}');
});
