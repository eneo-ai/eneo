import prettier from "eslint-config-prettier";
import js from "@eslint/js";
import svelte from "eslint-plugin-svelte";
import globals from "globals";
import ts from "typescript-eslint";
import intric from "@intric/eslint-plugin";

export default ts.config(
  js.configs.recommended,
  ...ts.configs.recommended,
  ...svelte.configs["flat/recommended"],
  prettier,
  ...svelte.configs["flat/prettier"],
  ...intric.configs.recommended,
  {
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node
      }
    }
  },
  {
    files: ["**/*.svelte", "**/*.svelte.ts"],

    languageOptions: {
      parserOptions: {
        parser: ts.parser
      }
    }
  },
  {
    ignores: ["build/", ".svelte-kit/", "dist/", "**/paraglide/"]
  },
  {
    // Block hardcoded human-facing text — every human-facing string must go
    // through paraglide (m.*). Enforced across the whole web app.
    // The `ignore` patterns below allow genuinely non-translatable literals
    // inline (brand, keyboard keys, technical identifiers). They are matched
    // against the trimmed text, so they are position-independent — unlike
    // inline eslint-disable comments, prettier reflowing markup cannot break
    // them.
    files: ["**/*.svelte"],
    rules: {
      "intric/no-hardcoded-text": [
        "error",
        {
          ignore: [
            "Eneo\\.ai", // product brand, used in page <title>s
            "^(sk|pk)_$", // API key type prefixes
            "^ENEO_[A-Z_]+$", // environment variable names
            "^(Ctrl|Enter|Shift|Alt|Cmd|Tab|Esc)$" // keyboard keys in <kbd>
          ]
        }
      ]
    }
  },
  {
    // Block raw colors in class attributes — every color must go through eneo's
    // semantic design tokens (bg-negative-dimmer, text-warning-stronger, …) so
    // it adapts to light/dark via `data-theme`. Tailwind palette utilities
    // (bg-orange-50) and arbitrary literals (bg-[#fff]) bypass the theme and the
    // `dark:` variant is inert here (no `.dark` class is ever set).
    //
    // Currently "warn": there is a backlog of pre-existing raw colors to burn
    // down (see frontend/COLORS.md). Flip to "error" once the backlog is clear.
    files: ["**/*.svelte"],
    rules: {
      "intric/no-raw-color": "warn"
    }
  },
  {
    rules: {
      "no-undef": "off",
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrors: "none"
        }
      ]
    }
  }
);
