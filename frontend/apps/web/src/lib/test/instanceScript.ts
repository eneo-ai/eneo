import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { parse } from "svelte/compiler";
import { ModuleKind, ScriptTarget, transpileModule } from "typescript";

/**
 * Run a Svelte page's actual `<script>` instance block in Node.
 *
 * Server-side compilation strips `onMount` and other client lifecycle code,
 * and browser mode cannot replace globals such as `window.opener`. These
 * helpers execute the real instance script with only framework and browser
 * boundaries swapped out, so the page logic under test is the shipped code.
 *
 * TypeScript elides imports the script never uses as values, such as
 * components and helpers that only appear in the markup. `modules` therefore
 * needs an entry for each import the script itself calls; anything else fails
 * loudly instead of letting a half-stubbed page pass.
 */
export function readInstanceScript(component: URL): string {
  const source = readFileSync(component, "utf8");
  const instance = parse(source, { modern: true }).instance;
  if (instance === null) throw new Error(`${component.pathname} has no instance script`);
  const content = instance.content;
  if (
    !("start" in content) ||
    !("end" in content) ||
    typeof content.start !== "number" ||
    typeof content.end !== "number"
  ) {
    throw new Error(`${component.pathname} script has no source offsets`);
  }
  return transpileModule(source.slice(content.start, content.end), {
    compilerOptions: { module: ModuleKind.CommonJS, target: ScriptTarget.ES2022 }
  }).outputText;
}

type InstanceScriptOptions = {
  /** Replacements for the script's imports, keyed by module specifier. */
  modules: Record<string, unknown>;
  /** Globals visible to the script: Svelte runes, browser objects, timers. */
  globals: Record<string, unknown>;
  /** Code appended after the script, for example to export local functions. */
  epilogue?: string;
  /** Name shown in stack traces and import errors. */
  filename: string;
};

export function runInstanceScript<T extends object>(
  script: string,
  { modules, globals, epilogue = "", filename }: InstanceScriptOptions
): T {
  const exports = {} as T;
  runInNewContext(
    `${script}\n${epilogue}`,
    {
      exports,
      require: (name: string) => {
        if (name in modules) return modules[name];
        throw new Error(`Unexpected ${filename} import: ${name}`);
      },
      ...globals
    },
    { timeout: 1000, filename }
  );
  return exports;
}
