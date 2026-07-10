/*
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { browser } from "$app/environment";

// The create dialog hands the user's task description to the AI builder route
// via sessionStorage. The seed is space-scoped and consumed exactly once: a
// present seed makes the AI builder start a fresh session instead of resuming
// a recoverable draft, so the handoff stays deterministic.
const SEED_KEY_PREFIX = "eneo:flows:ai-builder-seed:";

function seedKey(spaceId: string): string {
  return `${SEED_KEY_PREFIX}${spaceId}`;
}

export function writeAIBuilderSeed(spaceId: string, prompt: string): void {
  if (!browser) return;
  const trimmed = prompt.trim();
  if (!trimmed) return;
  try {
    sessionStorage.setItem(seedKey(spaceId), trimmed);
  } catch {
    // Storage full or unavailable — the user lands in the AI builder and can
    // type the description again; never block navigation on this.
  }
}

export function consumeAIBuilderSeed(spaceId: string): string | null {
  if (!browser) return null;
  try {
    const value = sessionStorage.getItem(seedKey(spaceId));
    if (value === null) return null;
    sessionStorage.removeItem(seedKey(spaceId));
    return value;
  } catch {
    return null;
  }
}
