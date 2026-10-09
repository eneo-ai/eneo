import type { WidgetPublicConfig } from "@eneo/eneo-js";
import { launcherColors, type LauncherColors } from "./contrast";

/**
 * What the loader asks for before it shows the launcher: the saved settings
 * that decide how and where it appears, so an edit or a template publication
 * reaches every site without a new snippet. Mirrors `WidgetSettings` in
 * packages/widget-loader/src/protocol.ts.
 */
export type WidgetLauncherSettings = {
  /** `auto` follows the host page. */
  language: WidgetPublicConfig["language"];
  position: "bottom-right" | "bottom-left";
  colors: LauncherColors;
};

export function launcherSettings(config: WidgetPublicConfig): WidgetLauncherSettings {
  return {
    language: config.language,
    position: config.theme.position ?? "bottom-right",
    colors: launcherColors(config.theme)
  };
}
