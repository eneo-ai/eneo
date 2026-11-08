/*
    Copyright (c) 2026 Sundsvalls Kommun
*/

import type { IconNode } from "@lucide/svelte";

/**
 * Template icons are picked by name from the whole Lucide set, so they cannot
 * be tree-shaken to a fixed list. The set comes as data: every icon's SVG
 * nodes in one module (plugins/lucide-icon-data.js), drawn by LucideSvg.svelte,
 * rather than a Svelte component per icon that the build would have to
 * compile. It is about 90 KB gzipped, so it is loaded here on
 * demand and kept off the startup path: only surfaces that render a template
 * icon or open the icon picker fetch it, once, and the immutable chunk is
 * cached after that.
 */

/** Lucide's name for an icon (the `lucide-<name>` class) and its SVG nodes. */
export type LucideIconData = { name: string; iconNode: IconNode };

export type LucideIconSet = (typeof import("virtual:lucide-icon-data"))["default"];

export type LucideIconRegistry = {
  /** Current icon names in PascalCase: what the picker offers. */
  names: string[];
  /**
   * The icon for a stored name. Lucide keeps aliases for icons it has renamed
   * (`home` is now `house`), so names saved from older versions still resolve.
   */
  get(name: string | null | undefined): LucideIconData | null;
};

export function createLucideRegistry(set: LucideIconSet): LucideIconRegistry {
  const icons = new Map(
    Object.entries(set.icons).map(([key, [name, iconNode]]) => [key, { name, iconNode }])
  );
  const aliases = new Map(Object.entries(set.aliases));
  const find = (key: string) => {
    const current = aliases.get(key);
    return icons.get(key) ?? (current ? icons.get(current) : undefined);
  };
  return {
    names: [...icons.keys()].sort(),
    get(name) {
      if (!name) return null;
      const key = toPascalCase(name);
      // @lucide/svelte also exports each icon and alias as `Lucide<Name>` and
      // `<Name>Icon`; the plugin checks that the package still does.
      return (
        find(key) ??
        (key.startsWith("Lucide") ? find(key.slice("Lucide".length)) : undefined) ??
        (key.endsWith("Icon") ? find(key.slice(0, -"Icon".length)) : undefined) ??
        null
      );
    }
  };
}

let registry: Promise<LucideIconRegistry> | undefined;

/** The full Lucide registry, fetched on first use and shared afterwards. */
export function loadLucideIcons(): Promise<LucideIconRegistry> {
  registry ??= import("virtual:lucide-icon-data").then(
    (module) => createLucideRegistry(module.default),
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

/** The icon for a stored name, or null when unset or unknown. */
export async function loadLucideIcon(
  name: string | null | undefined
): Promise<LucideIconData | null> {
  if (!name) return null;
  const icons = await loadLucideIcons();
  return icons.get(name);
}

/** Like loadLucideIcon, but a failed download yields null instead of rejecting. */
export function loadLucideIconOrNull(
  name: string | null | undefined
): Promise<LucideIconData | null> {
  return loadLucideIcon(name).catch(() => null);
}
