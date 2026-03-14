import { m } from "$lib/paraglide/messages";

type MessageFunction = (
  inputs?: Record<string, unknown>,
  options?: Record<string, unknown>
) => string;

export function apiKeysMessage(
  key: string,
  fallback: string,
  inputs: Record<string, unknown> = {}
): string {
  const fn = (m as unknown as Record<string, MessageFunction | undefined>)[key];
  if (typeof fn !== "function") {
    return fallback;
  }
  return fn(inputs);
}
