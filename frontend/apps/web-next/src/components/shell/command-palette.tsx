"use client";

import {
  CommandPalette,
  CommandPaletteFooter,
  CommandPaletteInput,
  useCommandPaletteContext
} from "@astryxdesign/core/CommandPalette";
import { Kbd } from "@astryxdesign/core/Kbd";
import type { SearchableItem, SearchSource } from "@astryxdesign/core/Typeahead";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import {
  Globe,
  Library,
  MessageSquare,
  Plus,
  Shield,
  SquarePen,
  User,
  type LucideIcon
} from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useMemo, useRef } from "react";
import { EntityAvatar } from "@/components/composites/entity-avatar";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { dashboardQueryOptions } from "@/app/(app)/dashboard/queries";
import { spaceQueryOptions, spacesListQueryOptions } from "@/features/spaces/space";
import { adminNavGroups } from "./admin-nav-items";
import { recentConversationsQueryOptions } from "./nav-data";
import {
  bootstrapEntries,
  buildPaletteEntries,
  searchEntries,
  splitMatch,
  type PaletteData,
  type PaletteEntry,
  type PaletteGroup,
  type PalettePermissions
} from "./palette-items";
import { spaceRouteIdFromPath } from "./routes";
import { useShell } from "./shell-context";

type PaletteItem = SearchableItem<{ group: string; entry: PaletteEntry }>;

/** Conversations the palette searches (the nav shows 5; searching deserves more). */
const PALETTE_CONVERSATIONS = 20;

const ICONS: Record<Extract<PaletteEntry["visual"], { type: "icon" }>["icon"], LucideIcon> = {
  personal: User,
  conversation: MessageSquare,
  collection: Library,
  website: Globe,
  compose: SquarePen,
  create: Plus,
  admin: Shield
};

async function settle<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise;
  } catch {
    return null;
  }
}

/**
 * Loads what the palette searches, lazily (only once it opens) and from the
 * shared query cache, so data the page already fetched is reused. A source
 * that fails just contributes no results.
 */
async function loadPaletteData(
  queryClient: QueryClient,
  currentSpaceRouteId: string | null
): Promise<PaletteData> {
  const [dashboard, spaces, currentSpace] = await Promise.all([
    settle(queryClient.ensureQueryData(dashboardQueryOptions(browserApi))),
    settle(queryClient.ensureQueryData(spacesListQueryOptions(browserApi))),
    currentSpaceRouteId
      ? settle(queryClient.ensureQueryData(spaceQueryOptions(browserApi, currentSpaceRouteId)))
      : Promise.resolve(null)
  ]);
  const personalAssistantId = dashboard?.spaces.items.find((space) => space.personal)
    ?.default_assistant?.id;
  const conversations = personalAssistantId
    ? await settle(
        queryClient.ensureQueryData(
          recentConversationsQueryOptions(browserApi, personalAssistantId, PALETTE_CONVERSATIONS)
        )
      )
    : null;

  return {
    dashboard,
    spaces,
    conversations: conversations ?? [],
    currentSpace:
      currentSpace && currentSpaceRouteId
        ? { routeId: currentSpaceRouteId, space: currentSpace }
        : null
  };
}

function Highlighted({ text, query }: { text: string; query: string }) {
  const parts = splitMatch(text, query);
  if (!parts) return <>{text}</>;
  return (
    <>
      {parts.before}
      <strong className="text-ax-text-accent font-semibold">{parts.match}</strong>
      {parts.after}
    </>
  );
}

function EntryVisual({ entry }: { entry: PaletteEntry }) {
  if (entry.visual.type === "entity") {
    return <EntityAvatar id={entry.visual.id} name={entry.visual.name} size="md" />;
  }
  const Glyph = ICONS[entry.visual.icon];
  return (
    <span
      aria-hidden="true"
      className="bg-ax-muted text-ax-text-secondary rounded-ax-inner flex size-8 shrink-0 items-center justify-center"
    >
      <Glyph className="size-4" />
    </span>
  );
}

function EntryContent({ entry }: { entry: PaletteEntry }) {
  const query = useCommandPaletteContext()?.search ?? "";
  return (
    <span className="flex min-w-0 flex-1 items-center gap-3">
      <EntryVisual entry={entry} />
      <span className="flex min-w-0 flex-col leading-tight">
        <span className="truncate font-medium">
          <Highlighted text={entry.label} query={query} />
        </span>
        {entry.subtitle ? (
          <span className="text-ax-text-secondary truncate text-xs">
            <Highlighted text={entry.subtitle} query={query} />
          </span>
        ) : null}
      </span>
    </span>
  );
}

function Hint({ keys, keyName, label }: { keys: string[]; keyName: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span aria-hidden="true" className="flex items-center gap-1">
        {keys.map((key) => (
          <Kbd key={key} keys={key} />
        ))}
      </span>
      <span className="sr-only">{keyName}:</span>
      {label}
    </span>
  );
}

/**
 * The ⌘K command palette (Astryx CommandPalette): a modal dialog with a
 * labelled combobox that searches assistants, spaces, personal conversations,
 * the current space's knowledge and actions (admin pages for admins). Mounted
 * the first time it opens; data loads then, never on page load.
 */
export default function ShellCommandPalette({
  isOpen,
  onOpenChange,
  onCreateSpace
}: {
  isOpen: boolean;
  onOpenChange: (isOpen: boolean) => void;
  onCreateSpace: () => void;
}) {
  const t = useTranslations();
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const { can, settings } = useAppContext();
  const { prepareNavigation } = useShell();
  const entriesById = useRef(new Map<string, PaletteEntry>());
  const currentSpaceRouteId = spaceRouteIdFromPath(pathname);

  const groupLabels: Record<PaletteGroup, string> = {
    assistants: t("assistants"),
    spaces: t("shell_spaces"),
    conversations: t("shell_conversations"),
    knowledge: t("knowledge"),
    actions: t("actions")
  };

  const permissions: PalettePermissions = {
    canCreateSpace: can("shared_spaces"),
    isAdmin: can("admin"),
    adminGroups: adminNavGroups({
      usingTemplates: Boolean(settings.using_templates),
      canManageModules: can("modules")
    })
  };
  // Rebuilt when these change; the data itself comes from the query cache.
  const permissionsKey = JSON.stringify([
    permissions.canCreateSpace,
    permissions.isAdmin,
    settings.using_templates,
    can("modules")
  ]);

  const searchSource = useMemo<SearchSource<PaletteItem>>(() => {
    const toItems = (entries: PaletteEntry[]): PaletteItem[] => {
      for (const entry of entries) entriesById.current.set(entry.id, entry);
      return entries.map((entry) => ({
        id: entry.id,
        label: entry.label,
        auxiliaryData: { group: groupLabels[entry.group], entry }
      }));
    };
    const load = async () =>
      buildPaletteEntries(await loadPaletteData(queryClient, currentSpaceRouteId), permissions, t);
    return {
      bootstrap: async () => toItems(bootstrapEntries(await load())),
      search: async (query: string) => toItems(searchEntries(await load(), query))
    };
    // groupLabels/permissions/t are derived from the listed inputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryClient, currentSpaceRouteId, permissionsKey, t]);

  function run(id: string) {
    const entry = entriesById.current.get(id);
    if (!entry) return;
    if (entry.action.type === "create-space") {
      // Open once the palette has closed and returned focus, so the dialog
      // returns focus to the same place when it closes.
      window.setTimeout(onCreateSpace, 0);
      return;
    }
    prepareNavigation(entry.action.href);
    router.push(entry.action.href);
  }

  return (
    <CommandPalette<PaletteItem>
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      searchSource={searchSource}
      label={t("shell_palette_label")}
      width="min(640px, calc(100vw - 2rem))"
      input={
        <CommandPaletteInput
          label={t("shell_palette_input_label")}
          placeholder={t("shell_palette_placeholder")}
        />
      }
      renderItem={(item) =>
        item.auxiliaryData ? <EntryContent entry={item.auxiliaryData.entry} /> : item.label
      }
      emptySearchText={t("no_results")}
      onValueChange={run}
      footer={
        <CommandPaletteFooter>
          <Hint
            keys={["up", "down"]}
            keyName={t("shell_palette_key_arrows")}
            label={t("shell_palette_hint_navigate")}
          />
          <Hint
            keys={["enter"]}
            keyName={t("shell_palette_key_enter")}
            label={t("shell_palette_hint_open")}
          />
          <Hint keys={["escape"]} keyName={t("shell_palette_key_escape")} label={t("close")} />
          <span className="ms-auto hidden sm:inline">{t("shell_palette_scope")}</span>
        </CommandPaletteFooter>
      }
    />
  );
}
