import { join } from "node:path";

/** Where `bun run build:prelude` leaves the script evaluated before every user script. */
export const PRELUDE_PATH = join(import.meta.dir, "..", "..", "..", "..", "dist", "prelude", "compute.js");

let prelude: Promise<string> | undefined;
/** The prelude's source, read once per process. */
export function loadPrelude(): Promise<string> {
  prelude ??= (async () => {
    const file = Bun.file(PRELUDE_PATH);
    if (!(await file.exists()))
      throw new Error('The compute prelude is not built. Run "bun run build:prelude" first.');
    return file.text();
  })();
  return prelude;
}
