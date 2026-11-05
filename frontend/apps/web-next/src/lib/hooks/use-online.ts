import { onlineManager } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";

const subscribe = (onChange: () => void) => onlineManager.subscribe(onChange);

/**
 * Whether the browser is online: the same truth that pauses and resumes the
 * app's queries (TanStack's onlineManager, fed by the window's online and
 * offline events).
 */
export function useOnline(): boolean {
  return useSyncExternalStore(subscribe, () => onlineManager.isOnline());
}
