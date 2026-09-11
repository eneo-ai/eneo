/*
    Copyright (c) 2026 Sundsvalls Kommun
*/

import type { Component } from "svelte";

/**
 * Template icons are picked by name from the whole Lucide set, so they cannot
 * be tree-shaken to a fixed list. Importing the library statically for that
 * lookup put every icon (about 4 MB of JavaScript, 145 KB gzipped) into the
 * chunk the app loads before the first paint of every page. Loading it here on
 * demand keeps it off the startup path: only surfaces that render a template
 * icon or open the icon picker fetch it, once, and the immutable chunk is
 * cached after that.
 */

export type LucideIconComponent = Component<{ class?: string }>;
export type LucideIconRegistry = Record<string, LucideIconComponent>;

let registry: Promise<LucideIconRegistry> | undefined;

/** The full Lucide registry, fetched on first use and shared afterwards. */
export function loadLucideIcons(): Promise<LucideIconRegistry> {
  registry ??= import("lucide-svelte").then(
    (module) => module as unknown as LucideIconRegistry,
    (error: unknown) => {
      // Do not keep a failed download; the next caller retries the request.
      registry = undefined;
      throw error;
    }
  );
  return registry;
}

/** Icon names are stored in kebab-case; the registry keys are PascalCase. */
export function toPascalCase(name: string): string {
  return (
    name.charAt(0).toUpperCase() + name.slice(1).replace(/-([a-z])/g, (g) => g[1].toUpperCase())
  );
}

/** Registry keys back to the stored kebab-case form. */
export function toKebabCase(name: string): string {
  return name.replace(/([a-z0-9])([A-Z])/g, "$1-$2").toLowerCase();
}

/** The component for a stored icon name, or null when unset or unknown. */
export async function loadLucideIcon(
  name: string | null | undefined
): Promise<LucideIconComponent | null> {
  if (!name) return null;
  const icons = await loadLucideIcons();
  return icons[toPascalCase(name)] ?? null;
}

/** Like loadLucideIcon, but a failed download yields null instead of rejecting. */
export function loadLucideIconOrNull(
  name: string | null | undefined
): Promise<LucideIconComponent | null> {
  return loadLucideIcon(name).catch(() => null);
}
