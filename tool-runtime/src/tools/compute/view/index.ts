import { loadView } from "../../../views/load";
import type { ToolView } from "../../types";

/** The result view run_javascript brings. Copying the value is the one thing it asks of the browser. */
export function computeResultView(): Promise<ToolView> {
  return loadView("compute-result", "compute", {
    prefersBorder: true,
    permissions: { clipboardWrite: {} },
  });
}
