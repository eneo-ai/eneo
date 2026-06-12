import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
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
  }
]);

export default eslintConfig;
