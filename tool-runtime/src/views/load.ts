import { createHash } from "node:crypto";
import { join } from "node:path";
import type { ToolView } from "../tools/types";

/** Where `bun run build:views` leaves each view as one self-contained page. */
export const VIEWS_DIRECTORY = join(import.meta.dir, "..", "..", "dist", "views");

/**
 * A built view as a tool brings it. Its address carries the hash of its content, so a host
 * that keeps a copy sees a new release as a new view.
 */
export async function loadView(
  name: string,
  server: string,
  ui: Record<string, unknown>,
): Promise<ToolView> {
  const file = Bun.file(join(VIEWS_DIRECTORY, `${name}.html`));
  if (!(await file.exists()))
    throw new Error(`The ${name} view is not built. Run "bun run build:views" first.`);
  const html = await file.text();
  const hash = createHash("sha256").update(html).digest("hex").slice(0, 12);
  return { uri: `ui://${server}/${name}-${hash}.html`, html, ui };
}
