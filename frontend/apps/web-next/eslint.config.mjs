import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import eneo from "@eneo/eslint-plugin";

const generatedAndVendored = [
  "src/lib/api/schema.d.ts",
  "src/lib/i18n/**",
  "src/components/ai-elements/**",
  "src/components/ui/**",
  "src/app/global-error.tsx",
  "src/app/(app)/chat-mock/**",
  "src/**/*.test.{ts,tsx}"
];

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    plugins: {
      eneo
    }
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts"
  ]),
  {
    // Vendored AI Elements (shadcn-style editable source). Upstream patterns
    // occasionally trip strict rules; relax instead of forking every file.
    files: ["src/components/ai-elements/**"],
    rules: {
      "react-hooks/refs": "off",
      "react-hooks/static-components": "off",
      "@typescript-eslint/no-unused-vars": "off"
    }
  },
  {
    // Port the shared eneo color guardrail to web-next app source. Vendored
    // primitives are intentionally exempted above and should stay close to
    // their upstream implementations.
    files: ["src/**/*.{ts,tsx}"],
    ignores: generatedAndVendored,
    rules: {
      "eneo/no-raw-color": "error"
    }
  },
  {
    // Block hardcoded human-facing JSX text in app code; route copy through
    // next-intl messages instead.
    files: ["src/**/*.tsx"],
    ignores: generatedAndVendored,
    rules: {
      "eneo/no-hardcoded-text": [
        "error",
        {
          ignore: [
            "Eneo\\.ai",
            "^(web-next|· backend)$",
            "^https?://$",
            "^(CSV|JSON|JSONL|PDF|URL|HTTP|HTTPS|OIDC|MCP|API|ID)$",
            "^SharePoint$",
            "^s$",
            "^(Ctrl|Enter|Shift|Alt|Cmd|Tab|Esc)$"
          ]
        }
      ]
    }
  }
]);

export default eslintConfig;
