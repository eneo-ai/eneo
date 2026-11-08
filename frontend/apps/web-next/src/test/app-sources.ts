import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";

const srcDir = path.resolve(import.meta.dirname, "..");

/** One of the app's own source files: its path under src (with `/`) and its text. */
export type AppSource = { file: string; text: string };

/**
 * The app's .ts, .tsx and .css files under src, tests excluded, read once when a
 * test file imports this module. Reading the tree takes a fraction of a second
 * alone but many seconds on a busy runner, and file collection has no timeout,
 * so the tests that check the source only match text.
 */
export const appSources: readonly AppSource[] = readdirSync(srcDir, {
  recursive: true,
  encoding: "utf8"
})
  .filter((file) => /\.(tsx?|css)$/.test(file) && !/\.test\.tsx?$/.test(file))
  .sort()
  .map((file) => ({
    file: file.split(path.sep).join("/"),
    text: readFileSync(path.join(srcDir, file), "utf8")
  }));
