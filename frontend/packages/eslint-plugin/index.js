import fs from "fs";

import noIgnoredUnsub from "./rules/no-ignored-unsubscriber.js";
import noIgnoredRemoveHandler from "./rules/no-ignored-removehandler.js";
import noHardcodedText from "./rules/no-hardcoded-text.js";
import noRawColor from "./rules/no-raw-color.js";

const pkg = JSON.parse(
  fs.readFileSync(new URL("./package.json", import.meta.url), "utf8"),
);

/** @type {import("eslint").ESLint.Plugin} */
const plugin = {
  meta: {
    name: pkg.name,
    version: pkg.version,
  },
  configs: {},
  rules: {
    "no-ignored-unsubscriber": noIgnoredUnsub,
    "no-ignored-removehandler": noIgnoredRemoveHandler,
    "no-hardcoded-text": noHardcodedText,
    "no-raw-color": noRawColor,
  },
};

Object.assign(plugin.configs, {
  recommended: [
    {
      plugins: {
        intric: plugin,
      },
      rules: {
        "intric/no-ignored-unsubscriber": "error",
        "intric/no-ignored-removehandler": "error",
      },
    },
  ],
});

export default plugin;
