import prettier from "eslint-config-prettier";
import js from "@eslint/js";
import globals from "globals";

export default [
  js.configs.recommended,
  prettier,
  {
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node
      }
    },
    rules: {
      "no-unused-vars": [
        "error",
        {
          caughtErrors: "none"
        }
      ]
    }
  }
];
