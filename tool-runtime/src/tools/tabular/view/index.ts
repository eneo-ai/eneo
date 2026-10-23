import { loadView } from "../../../views/load";
import type { ToolView } from "../../types";

/** The table view query_table brings. Copying rows is the one thing it asks of the browser. */
export function queryResultView(): Promise<ToolView> {
  return loadView("query-result", "file-analysis", {
    prefersBorder: true,
    permissions: { clipboardWrite: {} },
  });
}
