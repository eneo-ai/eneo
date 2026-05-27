import { RuleTester } from "eslint";
import * as svelteParser from "svelte-eslint-parser";

import rule from "./no-hardcoded-text.js";

const ruleTester = new RuleTester({
  languageOptions: {
    parser: svelteParser,
    ecmaVersion: 2022,
    sourceType: "module",
  },
});

ruleTester.run("no-hardcoded-text", rule, {
  valid: [
    // Text routed through paraglide is fine.
    { filename: "Test.svelte", code: "<p>{m.hello()}</p>" },
    // Symbol-/number-only text has no letters and is allowed.
    { filename: "Test.svelte", code: "<span>—</span>" },
    { filename: "Test.svelte", code: "<span>123 · 45 %</span>" },
    // Human-facing attributes bound to a message are fine.
    { filename: "Test.svelte", code: "<img alt={m.avatar()} />" },
    // Non-human attribute literals are not flagged (class is not display text).
    { filename: "Test.svelte", code: '<div class="card">{m.title()}</div>' },
    // `ignore` lets genuinely non-translatable literals through.
    {
      filename: "Test.svelte",
      code: "<title>Eneo.ai – {m.dashboard()}</title>",
      options: [{ ignore: ["Eneo\\.ai"] }],
    },
    {
      filename: "Test.svelte",
      code: "<kbd>Ctrl</kbd>",
      options: [{ ignore: ["^(Ctrl|Enter)$"] }],
    },
  ],
  invalid: [
    // Bare hardcoded sentence in markup.
    {
      filename: "Test.svelte",
      code: "<p>Hello world</p>",
      errors: [{ messageId: "hardcodedText" }],
    },
    // Hardcoded human-facing attribute.
    {
      filename: "Test.svelte",
      code: '<img alt="A cat" />',
      errors: [{ messageId: "hardcodedAttr" }],
    },
    {
      filename: "Test.svelte",
      code: '<input placeholder="Search users" />',
      errors: [{ messageId: "hardcodedAttr" }],
    },
    // `ignore` must not over-match: text without the ignored pattern still fails.
    {
      filename: "Test.svelte",
      code: "<p>Dashboard</p>",
      options: [{ ignore: ["Eneo\\.ai"] }],
      errors: [{ messageId: "hardcodedText" }],
    },
  ],
});
