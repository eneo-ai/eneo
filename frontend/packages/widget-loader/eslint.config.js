import prettier from "eslint-config-prettier";
import js from "@eslint/js";
import globals from "globals";
import ts from "typescript-eslint";

export default ts.config(
  js.configs.recommended,
  ...ts.configs.recommended,
  prettier,
  {
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node
      }
    }
  },
  {
    // Pinned release assets are served byte for byte (SRI); never lint or rewrite them.
    ignores: ["dist/", "releases/"]
  }
);
