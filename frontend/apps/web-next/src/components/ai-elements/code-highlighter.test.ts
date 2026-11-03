import type { ThemeInput } from "@streamdown/code";
import { beforeEach, expect, it, vi } from "vitest";

const tokens = { tokens: [], fg: "#000", bg: "#fff" };
const createCodePlugin = vi.fn(() => ({ highlight: vi.fn(() => tokens) }));
vi.mock("@streamdown/code", () => ({ createCodePlugin }));

type Module = typeof import("./code-highlighter");
let highlighter: Module;

beforeEach(async () => {
  // The loaded plugin lives in module state: start each test without it.
  vi.resetModules();
  createCodePlugin.mockClear();
  highlighter = await import("./code-highlighter");
});

const themes: [ThemeInput, ThemeInput] = [
  "github-light-high-contrast",
  "github-dark-high-contrast"
];
const options = { code: "const a = 1;", language: "ts" as const, themes };

it("loads Shiki only when a block asks for colours, then hands them back", async () => {
  expect(highlighter.code.getThemes()).toEqual(themes);
  expect(createCodePlugin).not.toHaveBeenCalled();

  const callback = vi.fn();
  expect(highlighter.code.highlight(options, callback)).toBeNull();
  await vi.waitFor(() => expect(callback).toHaveBeenCalledWith(tokens));
  expect(createCodePlugin).toHaveBeenCalledTimes(1);

  // Loaded: the next block is answered by Shiki itself.
  expect(highlighter.code.highlight(options)).toBe(tokens);
  expect(createCodePlugin).toHaveBeenCalledTimes(1);
});
