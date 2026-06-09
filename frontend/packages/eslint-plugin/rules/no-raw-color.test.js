import { RuleTester } from "eslint";
import * as svelteParser from "svelte-eslint-parser";

import rule from "./no-raw-color.js";

const ruleTester = new RuleTester({
  languageOptions: {
    parser: svelteParser,
    ecmaVersion: 2022,
    sourceType: "module",
  },
});

ruleTester.run("no-raw-color", rule, {
  valid: [
    // Semantic tokens are the whole point — never flagged.
    {
      filename: "T.svelte",
      code: '<div class="bg-negative-dimmer text-warning-stronger"></div>',
    },
    {
      filename: "T.svelte",
      code: '<div class="bg-secondary text-muted border-default"></div>',
    },
    // eneo tokens that merely contain a palette-ish word but no shade number.
    {
      filename: "T.svelte",
      code: '<div class="text-chart-red bg-accent-default"></div>',
    },
    // Non-color utilities with numbers are fine.
    {
      filename: "T.svelte",
      code: '<div class="h-14 gap-2 px-3 rounded-xl border-l-4"></div>',
    },
    // Dynamic class with only semantic tokens.
    {
      filename: "T.svelte",
      code: "<div class={ok ? 'bg-negative-default/10' : ''}></div>",
    },
    // Arbitrary non-color value (a size) is fine.
    { filename: "T.svelte", code: '<div class="w-[460px]"></div>' },
  ],
  invalid: [
    // Static raw palette utility.
    {
      filename: "T.svelte",
      code: '<div class="bg-orange-50"></div>',
      errors: [{ messageId: "rawColor" }],
    },
    // Raw palette inside a dynamic class expression.
    {
      filename: "T.svelte",
      code: '<div class={fail ? "bg-warning-dimmer/40 dark:bg-orange-950" : ""}></div>',
      errors: [{ messageId: "rawColor" }],
    },
    // Raw palette in a class directive.
    {
      filename: "T.svelte",
      code: "<div class:text-red-600={isError}></div>",
      errors: [{ messageId: "rawColor" }],
    },
    // Arbitrary hex color literal.
    {
      filename: "T.svelte",
      code: '<div class="bg-[#ffffff]"></div>',
      errors: [{ messageId: "rawColor" }],
    },
  ],
});
