import { m } from "$lib/paraglide/messages";
import type { EntryArea, EntryType } from "@eneo/whats-new";
import type { Component } from "svelte";
import {
  BookOpen,
  Bot,
  LayoutGrid,
  Layers,
  MessageSquare,
  Settings,
  Sparkles,
  User
} from "lucide-svelte";

// Both maps are typed exhaustively against the package's unions, and
// labels.test.ts asserts they cover the schema's runtime vocabularies, so a
// new area or type cannot reach users without a translated label.

export const typeLabel: Record<EntryType, () => string> = {
  new: m.whats_new_type_new,
  improved: m.whats_new_type_improved,
  fixed: m.whats_new_type_fixed
};

export const typeClass: Record<EntryType, string> = {
  new: "bg-positive-default/10 text-positive-stronger",
  improved: "bg-accent-default/10 text-accent-stronger",
  fixed: "bg-warning-default/10 text-warning-stronger"
};

export const areaLabel: Record<EntryArea, () => string> = {
  chat: m.whats_new_area_chat,
  assistants: m.whats_new_area_assistants,
  knowledge: m.whats_new_area_knowledge,
  spaces: m.whats_new_area_spaces,
  skills: m.whats_new_area_skills,
  account: m.whats_new_area_account,
  admin: m.whats_new_area_admin,
  platform: m.whats_new_area_platform
};

/** Label for a value that may come from a newer schema than this build knows. */
export function labelFor<K extends string>(map: Record<K, () => string>, key: K): string {
  const label = map[key];
  return label ? label() : key;
}

export const areaIcon: Record<EntryArea, Component> = {
  chat: MessageSquare as unknown as Component,
  assistants: Bot as unknown as Component,
  knowledge: BookOpen as unknown as Component,
  spaces: LayoutGrid as unknown as Component,
  skills: Sparkles as unknown as Component,
  account: User as unknown as Component,
  admin: Settings as unknown as Component,
  platform: Layers as unknown as Component
};
