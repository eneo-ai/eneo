/** Where the reader's choice to let tools run without asking is kept. */
export const AUTO_ACCEPT_TOOLS_STORAGE_KEY = "autoAcceptToolsEnabled";

/**
 * Whether the reader lets tools run without being asked each time. Tools run
 * automatically unless the reader has switched that off.
 */
export function toolsRunAutomatically(): boolean {
  try {
    return window.localStorage.getItem(AUTO_ACCEPT_TOOLS_STORAGE_KEY) !== "false";
  } catch {
    return true;
  }
}
