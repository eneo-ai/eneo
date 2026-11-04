import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import {
  NavHeadingMenu,
  NavHeadingMenuItem,
  useNavHeadingCloseContext
} from "@astryxdesign/core/NavMenu";
import { Divider } from "@astryxdesign/core/Divider";
import { SideNavHeading, SideNavItem } from "@astryxdesign/core/SideNav";
import { Skeleton } from "@astryxdesign/core/Skeleton";
import { useQuery } from "@tanstack/react-query";
import {
  BookMarked,
  BookOpenCheck,
  Building2,
  Check,
  Focus,
  LayoutGrid,
  MessagesSquare,
  RotateCcw,
  Settings,
  Shapes,
  Square,
  Star,
  Users,
  Workflow,
  type LucideIcon
} from "lucide-react";
import { useTranslations } from "use-intl";
import { Fragment, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { flushSync } from "react-dom";
import { blockingError } from "@/components/composites/query-state";
import { EntityAvatar } from "@/components/composites/entity-avatar";
import { iconUrl } from "@/components/composites/icon-url";
import { useAppContext } from "@/components/providers/app-context";
import { spaceRouteIdFromPath } from "@/components/shell/routes";
import { useShell } from "@/components/shell/shell-context";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError } from "@/lib/api/errors";
import { usePathname, useSearchParams } from "@/lib/navigation";
import {
  spaceHasPermission,
  spaceQueryOptions,
  spacesListQueryOptions,
  type ResourcePermission,
  type Space,
  type SpaceResource
} from "../space";
import { spaceNavGroups, type SpaceNavItem } from "./space-sections";

/** The icons of Svelte's space menu (`SpaceMenu.svelte`), in lucide. */
const ITEM_ICONS: Record<SpaceNavItem["id"] | "flows", LucideIcon> = {
  chat: MessagesSquare,
  overview: Focus,
  assistants: MessagesSquare,
  apps: Shapes,
  flows: Workflow,
  knowledge: BookMarked,
  skills: BookOpenCheck,
  members: Users,
  settings: Settings
};

/**
 * The space the sidebar shows: the committed route's, read from the cache
 * entry the `$spaceId` loader fills. The loader owns fetching it (and its
 * existence check), so the sidebar never requests it itself; the page's own
 * readers keep it fresh. A space that does not exist (404) shows no sidebar
 * content, even with an older copy cached. The shell sits outside the route's
 * SpaceProvider, so it cannot use `useSpace()`.
 */
function useNavSpace() {
  const routeId = spaceRouteIdFromPath(usePathname());
  const query = useQuery({ ...spaceQueryOptions(browserApi, routeId ?? ""), enabled: false });
  const missing = query.error instanceof EneoApiError && query.error.status === 404;
  return { routeId: missing ? null : routeId, query };
}

/**
 * Which row is current, as Svelte marks it: Chatt only without a chat
 * partner, Assistenter also on a chat with one (`?type=`).
 */
function useCurrentItem(): string | null {
  const [, , , section] = usePathname().split("/");
  const hasPartner = useSearchParams().get("type") !== null;
  if (section === "chat") return hasPartner ? "assistants" : "chat";
  if (section === "group-chats") return "assistants";
  return section ?? null;
}

function SpaceChip({ space }: { space: Space }) {
  const t = useTranslations();
  const name = space.personal
    ? t("personal_space")
    : space.organization
      ? t("organization_space")
      : space.name;
  return (
    <EntityAvatar
      id={space.id}
      name={name}
      src={iconUrl(space.icon_id)}
      icon={
        space.personal ? (
          <Star aria-hidden="true" />
        ) : space.organization ? (
          <Building2 aria-hidden="true" />
        ) : undefined
      }
      size="sm"
      className="size-5"
    />
  );
}

/**
 * Whether the switcher has opened, and how to close it. Astryx mounts a
 * heading's menu with the page, so a row per space would render, hidden, on
 * every page of a space; an account with many spaces paid for it on each one.
 * The menu is a native popover, and its `beforetoggle` renders the rows before
 * it shows; they then stay. A browser without the Popover API (Astryx shows the
 * menu by `display` there) gets the rows at once.
 *
 * Astryx closes a heading's menu on a pick only in the icon rail, and exports
 * nothing that closes it in the full sidebar, where the heading stays mounted
 * across spaces. `hidePopover` closes it there and returns focus to the heading.
 */
function useSwitcherPopover() {
  const marker = useRef<HTMLSpanElement>(null);
  const [opened, setOpened] = useState(
    () => typeof HTMLElement === "undefined" || !("showPopover" in HTMLElement.prototype)
  );
  useEffect(() => {
    const popover = marker.current?.closest<HTMLElement>("[popover]");
    if (opened || !popover) return;
    const open = (event: Event) => {
      if ((event as ToggleEvent).newState === "open") flushSync(() => setOpened(true));
    };
    popover.addEventListener("beforetoggle", open);
    return () => popover.removeEventListener("beforetoggle", open);
  }, [opened]);
  const closedByAstryx = useNavHeadingCloseContext() !== null;
  const close = () => {
    if (!closedByAstryx) marker.current?.closest<HTMLElement>("[popover]")?.hidePopover?.();
  };
  return { marker, opened, close };
}

/**
 * Astryx handles these on the heading's popover as well as on its menu, so left
 * to both an arrow moves two rows. Every other key goes on: Tab to the focus
 * trap, ⌘K to the palette, Escape to the popover.
 */
const LIST_KEYS = new Set(["ArrowUp", "ArrowDown", "Home", "End"]);

function keepListKeyInMenu(event: KeyboardEvent) {
  if (LIST_KEYS.has(event.key)) event.stopPropagation();
}

/**
 * Svelte's space selector (`SpaceSelector.svelte`): "Dina ytor", every
 * shared space (the current one checked) and "Skapa en ny yta" for those who
 * may. Picking a space opens its overview. The spaces scroll between the two,
 * as there, so neither leaves the screen however many spaces there are.
 */
function SwitcherMenu({ currentId }: { currentId: string | null }) {
  const t = useTranslations();
  const { can } = useAppContext();
  const { openCreateSpace } = useShell();
  const query = useQuery(spacesListQueryOptions(browserApi));
  const { marker, opened, close } = useSwitcherPopover();

  return (
    <NavHeadingMenu onKeyDown={keepListKeyInMenu}>
      <span ref={marker} hidden />
      <NavHeadingMenuItem label={t("your_spaces")} href="/spaces/list" onClick={close} />
      {blockingError(query) && (
        <NavHeadingMenuItem
          label={t("shell_spaces_retry")}
          description={t("shell_spaces_load_failed")}
          icon={<Icon icon={RotateCcw} />}
          onClick={() => {
            close();
            void query.refetch();
          }}
        />
      )}
      {/* A scroller a keyboard reaches by name: the rows are arrow-key stops (tabindex -1), which
          neither a browser nor axe counts as a way in. */}
      <div
        role="group"
        aria-label={t("your_spaces")}
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a menu's child, so it cannot be a region
        tabIndex={0}
        className="focus-visible:outline-ring flex max-h-[50dvh] flex-col gap-0.5 overflow-y-auto focus-visible:outline-2 focus-visible:-outline-offset-2"
      >
        {(opened ? (query.data ?? []) : [])
          .filter((space) => !space.personal && !space.organization)
          .map((space) => (
            <NavHeadingMenuItem
              key={space.id}
              href={`/spaces/${space.id}/overview`}
              onClick={close}
              label={
                <span className="flex min-w-0 items-center justify-between gap-2">
                  <span className="truncate">{space.name}</span>
                  {space.id === currentId && (
                    <Check aria-hidden="true" className="text-ax-accent size-4 shrink-0" />
                  )}
                </span>
              }
              icon={<EntityAvatar id={space.id} name={space.name} size="sm" />}
              // The current space, not the page: the sidebar's section link stays the only "page".
              aria-current={space.id === currentId ? "true" : undefined}
            />
          ))}
      </div>
      {can("shared_spaces") && (
        <NavHeadingMenuItem
          label={t("create_new_space")}
          onClick={() => {
            close();
            openCreateSpace();
          }}
        />
      )}
    </NavHeadingMenu>
  );
}

/**
 * The sidebar's heading on a space route: the personal and organisation
 * spaces a fixed label, a shared space the switcher. Its security class is the
 * subheading, so every space shows it (the organisation's too).
 */
export function SpaceNavHeading() {
  const t = useTranslations();
  const { routeId, query } = useNavSpace();
  const space = query.data;

  if (routeId === null) return null;
  if (!space) {
    if (!blockingError(query)) {
      return (
        <div aria-hidden="true" className="flex items-center gap-3 px-2 py-2">
          <Skeleton height={24} width={24} radius={2} />
          <Skeleton height={16} width="60%" radius={1} />
        </div>
      );
    }
    return (
      <div className="flex flex-col gap-1 px-2 py-1.5">
        <p className="text-ax-error text-xs">{t("shell_spaces_load_failed")}</p>
        <Button
          variant="ghost"
          size="sm"
          label={t("shell_spaces_retry")}
          icon={<Icon icon={RotateCcw} />}
          isLoading={query.isFetching}
          isInterruptible
          onClick={() => {
            if (!query.isFetching) void query.refetch();
          }}
        />
      </div>
    );
  }

  const fixed = space.personal || space.organization;
  return (
    <SideNavHeading
      heading={
        space.personal
          ? t("personal_space")
          : space.organization
            ? t("organization_space")
            : space.name
      }
      icon={<SpaceChip space={space} />}
      subheading={space.security_classification?.name ?? undefined}
      menu={fixed ? undefined : <SwitcherMenu currentId={space.id} />}
    />
  );
}

/** The space's sections in Svelte's groups, a divider between groups. */
export function SpaceNavSections() {
  const t = useTranslations();
  const { routeId, query } = useNavSpace();
  const current = useCurrentItem();
  const space = query.data;
  if (routeId === null || !space) return null;

  const can = (action: ResourcePermission, resource: SpaceResource) =>
    spaceHasPermission(space, action, resource);
  const groups = spaceNavGroups(space, can, routeId);

  return (
    <div className="flex flex-col gap-0.5">
      {groups.map((group, index) => (
        <Fragment key={group[0]!.id}>
          {index > 0 && <Divider className="my-2" />}
          {group.map((item) => (
            <SideNavItem
              key={item.id}
              label={t(item.id)}
              icon={ITEM_ICONS[item.id]}
              href={item.href}
              isSelected={current === item.id}
            />
          ))}
        </Fragment>
      ))}
    </div>
  );
}

/** `/spaces/list`: Svelte's "Välj en yta" selector over one row, "Dina ytor". */
export function SpacesListNavHeading() {
  const t = useTranslations();
  return (
    <SideNavHeading
      heading={t("select_a_space")}
      icon={<Square aria-hidden="true" className="size-4" />}
      menu={<SwitcherMenu currentId={null} />}
    />
  );
}

export function SpacesListNavSections() {
  const t = useTranslations();
  return <SideNavItem label={t("your_spaces")} icon={LayoutGrid} href="/spaces/list" isSelected />;
}
