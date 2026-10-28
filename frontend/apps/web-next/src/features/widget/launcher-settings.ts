import type { WidgetPublicConfig } from "@eneo/eneo-js";
import { launcherColors, type LauncherColors } from "./contrast";
import type { LauncherPersona } from "./embed-bridge";
import { personaView } from "./persona";

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
  /** Who answers, for the launcher's name; the avatar only when it is the launcher. */
  persona: LauncherPersona | null;
};

/** `appOrigin` is where the avatar is served from: this app, through its icon proxy. */
export function launcherSettings(
  config: WidgetPublicConfig,
  appOrigin: string
): WidgetLauncherSettings {
  const persona = personaView(config, appOrigin);
  return {
    language: config.language,
    position: config.theme.position ?? "bottom-right",
    colors: launcherColors(config.theme),
    persona: persona
      ? { name: persona.name, avatar_url: persona.inLauncher ? persona.avatarUrl : null }
      : null
  };
}
