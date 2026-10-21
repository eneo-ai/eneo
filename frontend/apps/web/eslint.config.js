import { readFileSync } from "node:fs";
import prettier from "eslint-config-prettier";
import js from "@eslint/js";
import svelte from "eslint-plugin-svelte";
import globals from "globals";
import ts from "typescript-eslint";
import eneo from "@eneo/eslint-plugin";

// Lucide keeps renamed icons as deprecated aliases (`Loader2` → `LoaderCircle`) and drops them in
// later majors. Read them from the installed package so the rule below tracks the version we use.
const lucideAliases = readFileSync(
  new URL("./aliases/aliases.js", import.meta.resolve("@lucide/svelte")),
  "utf8"
);
const deprecatedLucideIcons = [
  ...lucideAliases.matchAll(
    /@deprecated[^\n]*\{@link (\w+)\}[^\n]*\n\s*default as (\w+) \} from '\.\.\/icons\/([\w-]+)\.js'/g
  )
].map(([, current, alias, file]) => ({ current, alias, file }));

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
    // A full-document navigation in a browser-mode component test unloads
    // the Vitest tester iframe and the run hangs instead of failing. Going
    // through $lib/core/navigation keeps it mockable.
    files: ["src/**/*.{svelte,js,ts}"],
    ignores: ["src/lib/core/navigation.ts"],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector:
            "CallExpression[callee.property.name=/^(assign|replace)$/][callee.object.name='location'], CallExpression[callee.property.name=/^(assign|replace)$/][callee.object.property.name='location']",
          message: "Navigate with assignLocation from $lib/core/navigation, which tests can mock."
        }
      ]
    }
  },
  {
    // Vendored shadcn-svelte files stay as upstream ships them.
    files: ["src/**/*.{svelte,js,ts}"],
    ignores: ["src/lib/components/ui/**"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "@lucide/svelte",
              importNames: deprecatedLucideIcons.map(({ alias }) => alias),
              message:
                "Deprecated Lucide alias: import the current icon name named in its @deprecated note."
            }
          ],
          patterns: [
            {
              group: deprecatedLucideIcons.map(({ file }) => `@lucide/svelte/icons/${file}`),
              message:
                "Deprecated Lucide alias: import the current icon file named in its @deprecated note."
            }
          ]
        }
      ]
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
