import prettier from "eslint-config-prettier";
import js from "@eslint/js";
import svelte from "eslint-plugin-svelte";
import globals from "globals";
import ts from "typescript-eslint";
import eneo from "@eneo/eslint-plugin";

export default ts.config(
  js.configs.recommended,
  ...ts.configs.recommended,
  ...svelte.configs["flat/recommended"],
  prettier,
  ...svelte.configs["flat/prettier"],
  ...eneo.configs.recommended,
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
    // `**/dev/**` routes are throwaway UI prototypes / previews (see their
    // READMEs); their demo copy is intentionally not translated, so exempt them
    // from the lint rules that would otherwise force paraglide messages.
    ignores: [
      "build/",
      ".svelte-kit/",
      ".svelte-kit-e2e/",
      "coverage/",
      "playwright-report/",
      "test-results/",
      "dist/",
      "**/paraglide/",
      "**/dev/**"
    ]
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
      "eneo/no-hardcoded-text": [
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
    // Block raw colors in UI source — every color must go through eneo's
    // semantic design tokens (bg-negative-dimmer, text-warning-stronger, …) so
    // it adapts to light/dark via `data-theme`. This also covers class strings
    // assembled in scripts, generated markup, and component <style> blocks.
    //
    // Existing violations are tracked in eslint-suppressions.json. ESLint only
    // suppresses that per-file count, so newly added violations fail CI.
    files: ["src/**/*.{svelte,js,ts}"],
    rules: {
      "eneo/no-raw-color": "error"
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
