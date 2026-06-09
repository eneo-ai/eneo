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
    // Semantic variables are allowed in component CSS.
    {
      filename: "T.svelte",
      code: "<style>.item { color: var(--text-primary); }</style>",
    },
    // HTML entities are not hex colors.
    {
      filename: "T.svelte",
      code: '<script>const escaped = "&#123;";</script>',
    },
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
      errors: [{ messageId: "rawColor" }, { messageId: "darkVariant" }],
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
    {
      filename: "T.svelte",
      code: '<div class="bg-white text-black"></div>',
      errors: [{ messageId: "rawColor" }, { messageId: "rawColor" }],
    },
    {
      filename: "T.svelte",
      code: '<div class="dark:bg-negative-dimmer"></div>',
      errors: [{ messageId: "darkVariant" }],
    },
    {
      filename: "T.svelte",
      code: '<script>const cls = "bg-red-500";</script><div class={cls}></div>',
      errors: [{ messageId: "rawColor" }],
    },
    {
      filename: "T.svelte",
      code: '<div class="bg-[var(--color-ui-red-500)]"></div>',
      errors: [{ messageId: "rawColor" }],
    },
    {
      filename: "T.svelte",
      code: '<div class="bg-[lch(50%_20_30)]"></div>',
      errors: [{ messageId: "rawColor" }],
    },
    {
      filename: "T.svelte",
      code: "<style>.item { color: #fff; box-shadow: 0 0 1px rgb(0 0 0 / 20%); }</style>",
      errors: [{ messageId: "rawColor" }, { messageId: "rawColor" }],
    },
    {
      filename: "T.svelte",
      code: '<script>const html = `<span class="text-orange-600">x</span>`;</script>',
      errors: [{ messageId: "rawColor" }],
    },
  ],
});
