import { loadView } from "../../../views/load";
import type { ToolView } from "../../types";

/** The interactive forecast create_forecast brings. */
export function forecastView(): Promise<ToolView> {
  return loadView("forecast", "forecast", { prefersBorder: true });
}
