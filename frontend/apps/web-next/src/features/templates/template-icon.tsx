"use client";

import { DynamicIcon, iconNames, type IconName } from "lucide-react/dynamic";
import type { LucideProps } from "lucide-react";

/**
 * Template icons are picked by name from the whole Lucide set, so they cannot
 * be imported one by one. lucide-react's dynamic entry lists every name (and
 * the aliases Lucide keeps for renamed icons, `home` for `house`) and fetches
 * each icon as its own small chunk when it is first drawn. The list (about
 * 60 KB gzipped with its chunk map) goes with the code that imports this
 * module, so keep it to the template surfaces.
 */
export const TEMPLATE_ICON_NAMES: readonly IconName[] = iconNames;

/** Lower-case letters and digits only: `MessageSquare`, `message-square` → `messagesquare`. */
export function compactIconName(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]/g, "");
}

let byCompactName: Map<string, IconName> | undefined;

/**
 * The Lucide name for a stored icon name, or null when unset or unknown.
 * Names are stored in kebab-case; the Svelte picker derived them from Lucide's
 * PascalCase names (`arrow-down01` for `ArrowDown01`, which lucide-react calls
 * `arrow-down-0-1`), so they are matched without their dashes.
 */
export function templateIconName(name: string | null | undefined): IconName | null {
  if (!name) return null;
  byCompactName ??= new Map(TEMPLATE_ICON_NAMES.map((icon) => [compactIconName(icon), icon]));
  return byCompactName.get(compactIconName(name)) ?? null;
}

/**
 * The name a picked icon is stored under: its Lucide name without a dash
 * before a digit (`building-2` → `building2`, `arrow-down-0-1` →
 * `arrow-down01`). That is the form the Svelte app stores and the only one its
 * reader resolves, since it capitalises just the letters after a dash;
 * templateIconName reads both forms.
 */
export function storedTemplateIconName(name: IconName): string {
  return name.replace(/-(?=\d)/g, "");
}

/** A template's Lucide icon by its stored name; nothing for an unset or unknown name. */
export function TemplateIcon({
  name,
  ...props
}: { name: string | null | undefined } & LucideProps) {
  const icon = templateIconName(name);
  return icon ? <DynamicIcon name={icon} aria-hidden="true" {...props} /> : null;
}
