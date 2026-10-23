import { loadView } from "../../../views/load";
import type { ToolView } from "../../types";

/** The interactive chart create_chart brings. */
export function chartView(): Promise<ToolView> {
  return loadView("chart", "charts", { prefersBorder: true });
}
