import {
  DropdownMenu,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem
} from "@astryxdesign/core/DropdownMenu";
import { IconButton } from "@astryxdesign/core/IconButton";
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import { Button } from "@astryxdesign/core/Button";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { useMediaQuery } from "@astryxdesign/core/hooks";
import { Bug, ChevronDown, Menu, Pencil, SquarePen } from "lucide-react";
import { MEDIA } from "@/lib/breakpoints";
import { useRouter } from "@/lib/navigation";
import { useTranslations } from "use-intl";
import { ClassificationToken } from "@/components/composites/classification-token";
import { EntityAvatar } from "@/components/composites/entity-avatar";
import { iconUrl } from "@/components/composites/icon-field";
import { OPEN_NAV_EVENT } from "@/components/shell/routes";
import { ConnectionBanner } from "@/components/shell/connection-banner";
import { OWN_MOBILE_HEADER } from "@/components/shell/shell-context";
import { displayPartnerName } from "@/lib/chat/partner-name";
import type { ChatPartner } from "@/lib/chat/types";
import { cn } from "@/lib/utils";
import type { ChatPartnerSwitcherItem } from "./partner-switcher";
import { BrandMark } from "./start-state";
import { CHAT_PANEL_IDS, type ChatTab } from "./chat-url";

/**
 * Opens the app shell's navigation drawer on phones: the shell hides its own
 * top bar while this header is shown and listens for OPEN_NAV_EVENT.
 */
function AppMenuButton() {
  const t = useTranslations();
  return (
    <IconButton
      label={t("chat_open_menu")}
      icon={<Menu className="size-5" />}
      variant="ghost"
      onClick={() => window.dispatchEvent(new CustomEvent(OPEN_NAV_EVENT))}
      className="size-11"
    />
  );
}

type SwitcherVariant = "header" | "token" | "mobile";

function PartnerTile({
  partner,
  size
}: {
  partner: Pick<ChatPartner, "id" | "name" | "iconId" | "type" | "personalSpace">;
  size: "sm" | "md";
}) {
  const t = useTranslations();
  if (partner.type === "default-assistant" && !partner.iconId) {
    return (
      <span
        aria-hidden="true"
        className={cn(
          "bg-ax-accent-muted flex shrink-0 items-center justify-center",
          size === "md" ? "size-[30px] rounded-[9px]" : "size-6 rounded-full"
        )}
      >
        <BrandMark className={size === "md" ? "size-4" : "size-3.5"} />
      </span>
    );
  }
  return (
    <EntityAvatar
      id={partner.id}
      name={displayPartnerName(partner, t)}
      src={iconUrl(partner.iconId)}
      size={size === "md" ? "md" : "sm"}
      className={size === "md" ? "size-[30px] rounded-[9px]" : "rounded-full"}
    />
  );
}

/** The space a partner belongs to, worth naming: not the personal space ("Personlig assistent"). */
function partnerSpace(partner: ChatPartner): string | null {
  return partner.personalSpace ? null : (partner.spaceName ?? null);
}

/** "…kommit?" stays as it is; "Upphandlingsanalys" becomes a sentence. */
const asSentence = (text: string) => (/[.!?…]$/.test(text) ? text : `${text}.`);

/**
 * The switcher's accessible name: what its face shows, in the face's order, so
 * a voice command that says what is seen reaches it (WCAG 2.5.3), then what the
 * face leaves out for room and what the button does. On a phone (decision 2):
 * "Upphandlingsanalys mot LOU. Upphandlingsassistenten Intern. I Upphandling.
 * Byt assistent"; from 768 px: "Upphandlingsassistenten. Upphandling · Claude
 * Haiku 4.5. Byt assistent"; the composer's token: "Upphandlingsassistenten. Byt
 * assistent".
 */
function switcherName(
  t: ReturnType<typeof useTranslations>,
  partner: ChatPartner,
  variant: SwitcherVariant,
  title: string | null,
  subtitle: string | null
): string {
  const name = displayPartnerName(partner, t);
  const space = partnerSpace(partner);
  const parts =
    variant === "token"
      ? [name]
      : variant === "header"
        ? [name, subtitle]
        : [
            title,
            [name, title === null ? space : null, partner.securityClassification]
              .filter(Boolean)
              .join(" "),
            title !== null && space ? t("chat_header_space_tail", { space }) : null
          ];
  return parts
    .filter((part): part is string => !!part)
    .map(asSentence)
    .concat(t("chat_header_switch"))
    .join(" ");
}

function SwitcherFace({
  partner,
  title = null,
  subtitle,
  variant,
  interactive
}: {
  partner: ChatPartner;
  /** The conversation's title, first on the phone face (decision 2); null before one starts. */
  title?: string | null;
  subtitle: string | null;
  variant: SwitcherVariant;
  interactive: boolean;
}) {
  const t = useTranslations();
  const name = displayPartnerName(partner, t);
  const chevron = interactive && (
    <ChevronDown aria-hidden="true" className="text-ax-text-secondary size-4 shrink-0" />
  );
  if (variant === "mobile") {
    // Two start-aligned lines: the title (or, before a conversation, the
    // assistant), then who answers and the space's security class. The
    // chevron sits beside the assistant, which is what the menu switches.
    // The spaces between the spans keep shown words apart for axe, which
    // joins text with no separator (flex drops them from the layout).
    const space = partnerSpace(partner);
    const classification = (
      <ClassificationToken
        variant="inline"
        name={partner.securityClassification}
        // A class name is short: the space or assistant gives way first.
        className="max-w-[45%] shrink-0"
      />
    );
    const line = "flex max-w-full min-w-0 items-center";
    const second = cn(line, "text-ax-text-secondary gap-1.5 text-[0.8125rem] leading-snug");
    if (title === null) {
      return (
        <span className="flex min-w-0 flex-col items-start text-start">
          <span className={cn(line, "gap-1 text-[1.0625rem] leading-snug font-semibold")}>
            <span className="truncate">{name}</span>
            {chevron}
          </span>{" "}
          {(space || partner.securityClassification) && (
            <span className={second}>
              {space && <span className="truncate">{space}</span>} {classification}
            </span>
          )}
        </span>
      );
    }
    return (
      <span className="flex min-w-0 flex-col items-start text-start">
        <span className="max-w-full truncate text-[1.0625rem] leading-snug font-semibold">
          {title}
        </span>{" "}
        <span className={second}>
          <span className="flex min-w-0 items-center gap-0.5">
            <span className="truncate">{name}</span>
            {/* Left out for room at 390px; the switcher's name and its menu say it. */}
            {space && <span className="sr-only">, {space}</span>}
            {chevron}
          </span>{" "}
          {classification}
        </span>
      </span>
    );
  }
  if (variant === "token") {
    return (
      <span className="flex min-w-0 items-center gap-1.5">
        <PartnerTile partner={partner} size="sm" />
        <span className="truncate">{name}</span>
        {chevron}
      </span>
    );
  }
  return (
    <span className="flex min-w-0 items-center gap-2.5">
      <PartnerTile partner={partner} size="md" />
      <span className="flex min-w-0 flex-col items-start leading-tight">
        <span className="max-w-full truncate font-semibold">{name}</span>{" "}
        {subtitle && (
          <span className="text-ax-text-secondary max-w-full truncate text-xs font-normal">
            {subtitle}
          </span>
        )}
      </span>
      {chevron}
    </span>
  );
}

/** Box of the selector (the menu button, or the static identity without a menu). */
const SWITCHER_CLASS: Record<SwitcherVariant, string> = {
  header:
    "text-ax-text flex h-[42px] max-w-[min(22rem,40vw)] min-w-0 items-center justify-start rounded-ax-element ps-1.5 pe-2 text-start text-sm pointer-coarse:h-11",
  token:
    "text-ax-text border-ax-border-control flex h-8 max-w-[min(16rem,40vw)] min-w-0 items-center justify-start rounded-full border ps-1 pe-2 text-[13px] font-semibold pointer-coarse:h-11",
  // Start-aligned (one control before it, two after); on an iPad held
  // upright no wider than its lines need.
  mobile:
    "text-ax-text flex h-auto min-h-11 min-w-0 flex-1 items-center justify-start rounded-ax-container py-1 ps-2 pe-1 text-start sm:max-w-[28rem]"
};

/** Menu value of a switcher item. */
function itemValue(item: Pick<ChatPartnerSwitcherItem, "type" | "id">): string {
  return `${item.type}:${item.id}`;
}

/**
 * The assistant selector: shows who you are talking to and, in a space,
 * opens the partner switcher (assistants and group chats of the space) as an
 * Astryx menu of radio items, so the current one is announced as selected.
 * Picking another opens its chat. Without switcher items it is a static
 * identity.
 */
export function PartnerSwitcher({
  partner,
  items,
  title = null,
  subtitle,
  variant
}: {
  partner: ChatPartner;
  items?: ChatPartnerSwitcherItem[];
  /** The conversation's title: the phone face shows it first (decision 2). */
  title?: string | null;
  subtitle: string | null;
  variant: SwitcherVariant;
}) {
  const t = useTranslations();
  const router = useRouter();
  const interactive = (items?.length ?? 0) > 1;

  if (!interactive) {
    return (
      <div className={cn(SWITCHER_CLASS[variant], variant === "token" && "border-transparent")}>
        <SwitcherFace
          partner={partner}
          title={title}
          subtitle={subtitle}
          variant={variant}
          interactive={false}
        />
      </div>
    );
  }

  const active = items!.find((item) => item.active);
  return (
    <DropdownMenu
      button={{
        label: switcherName(t, partner, variant, title, subtitle),
        variant: "ghost",
        className: SWITCHER_CLASS[variant],
        children: (
          <SwitcherFace
            partner={partner}
            title={title}
            subtitle={subtitle}
            variant={variant}
            interactive
          />
        )
      }}
      // The face draws its own chevron (beside the assistant's name on phones).
      hasChevron={false}
      alignment="start"
      menuWidth={288}
    >
      <DropdownMenuRadioGroup
        label={t("select_an_assistant")}
        value={active ? itemValue(active) : undefined}
        onChange={(value) => {
          const item = items!.find((candidate) => itemValue(candidate) === value);
          if (item && !item.active) router.push(item.href);
        }}
      >
        {items!.map((item) => (
          <DropdownMenuRadioItem
            key={itemValue(item)}
            value={itemValue(item)}
            label={displayPartnerName(
              {
                type: item.type === "default-assistant" ? "default-assistant" : "assistant",
                name: item.name,
                personalSpace: item.personalSpace
              },
              t
            )}
            icon={
              <PartnerTile
                partner={{
                  id: item.id,
                  name: item.name,
                  iconId: item.iconId ?? null,
                  type: item.type === "default-assistant" ? "default-assistant" : "assistant",
                  personalSpace: item.personalSpace
                }}
                size="sm"
              />
            }
          />
        ))}
      </DropdownMenuRadioGroup>
    </DropdownMenu>
  );
}

/** A row of the chat menu: an action, or a page it links (`href`). */
export type HeaderMenuItem = {
  label: string;
  onClick?: () => void;
  href?: string;
  variant?: "destructive";
};

export type ChatHeaderProps = {
  partner: ChatPartner;
  switcherItems?: ChatPartnerSwitcherItem[];
  /**
   * The page's h1: the conversation title, or what is happening while one
   * loads. null when the h1 is elsewhere: the start state's greeting, or the
   * message that a conversation could not be loaded.
   */
  title: string | null;
  /** A fixed model, shown under the partner's name ("space · model"). */
  modelName?: string | null;
  /**
   * The page's views as Svelte's chat page has them: Chatt, Historik and,
   * where the partner has them, Insikter. Beside the SideNav they are tabs; a
   * phone opens Historik as a sheet and switches Insikter from its menu.
   */
  view: { value: ChatTab; onChange: (value: ChatTab) => void; hasInsights: boolean };
  historyOpen: boolean;
  onToggleHistory: () => void;
  onNewConversation: () => void;
  /** Session actions (rename, delete) and the context meter. */
  menuItems: HeaderMenuItem[];
  /** The partner's editor: Redigera beside the SideNav, a menu row on a phone. */
  editHref?: string | null;
  /** Felsökning; isEnabled is false until a saved answer exists to inspect. */
  debug?: { isEnabled: boolean; onOpen: (trigger: HTMLElement) => void } | null;
  /** A space's default assistant before its first question: the selector lives in the composer. */
  minimal?: boolean;
};

/**
 * Chat header. From 768px (56px), as Svelte's: "Personlig assistent" or the
 * assistant selector, the conversation title (h1), the Chatt/Historik/Insikter
 * tabs, the space's security classification, Felsökning, Redigera, Ny
 * konversation and a menu for session actions. Below 768px (decision 2): the app menu (opens the shell's
 * drawer), the switcher with the conversation's title first and the
 * assistant and security class under it, new conversation and the same
 * menu.
 */
export function ChatHeader({
  partner,
  switcherItems,
  title,
  modelName,
  view,
  historyOpen,
  onToggleHistory,
  onNewConversation,
  menuItems,
  editHref = null,
  debug = null,
  minimal = false
}: ChatHeaderProps) {
  const t = useTranslations();
  const compact = useMediaQuery(`not all and ${MEDIA.xl}`);
  // Felsökning waits for a saved answer with its reason in a tooltip, which
  // touch cannot reach: on touch it shows once it can be opened.
  const coarse = useMediaQuery("(pointer: coarse)");
  const subtitle = [partner.spaceName, modelName].filter(Boolean).join(" · ") || null;
  const mobileMenu: HeaderMenuItem[] = [
    {
      label: historyOpen
        ? t("chat_history_close")
        : t("chat_history_with", { name: displayPartnerName(partner, t) }),
      onClick: onToggleHistory
    },
    ...(view.hasInsights
      ? [
          {
            label: view.value === "insights" ? t("chat") : t("insights"),
            onClick: () => view.onChange(view.value === "insights" ? "chat" : "insights")
          }
        ]
      : []),
    ...(editHref ? [{ label: t("chat_edit_assistant"), href: editHref }] : []),
    ...menuItems
  ];

  return (
    <>
      {/* Beside the SideNav, as Svelte's chat page header: who you talk to and
          the conversation's title, the views as tabs in the middle, then
          Felsökning, Redigera and Ny konversation. By what the space beside the
          SideNav holds, not the window: the title gives way, then the switcher
          down to its floor, and past that the buttons move to a row of their
          own, whole. */}
      <div className="border-ax-border wide:flex hidden min-h-14 shrink-0 flex-wrap items-center gap-x-3 gap-y-1.5 border-b py-1.5 ps-4 pe-3">
        <div className="flex min-w-48 flex-1 items-center gap-3">
          {(partner.type === "default-assistant" && partner.personalSpace) || minimal ? (
            <span className="min-w-0 truncate text-lg font-bold">
              {displayPartnerName(partner, t)}
            </span>
          ) : (
            <PartnerSwitcher
              partner={partner}
              items={switcherItems}
              subtitle={subtitle}
              variant="header"
            />
          )}
          {title !== null && view.value !== "chat" ? (
            // The selected tab already shows this name; the h1 stays for a screen reader.
            <h1 className="sr-only">{title}</h1>
          ) : title !== null ? (
            <>
              <span aria-hidden="true" className="bg-ax-border-strong h-[22px] w-px shrink-0" />
              <h1 className="text-ax-text-secondary min-w-0 shrink-[9999] truncate text-sm font-medium">
                {title}
              </h1>
            </>
          ) : null}
        </div>
        <TabList
          role="tablist"
          aria-label={t("main_views_available_for_current_resource")}
          value={view.value}
          onChange={(value) =>
            view.onChange(value === "history" || value === "insights" ? value : "chat")
          }
          size="sm"
          className="shrink-0"
        >
          <Tab value="chat" label={t("chat")} panelId={CHAT_PANEL_IDS.chat} />
          <Tab value="history" label={t("history")} panelId={CHAT_PANEL_IDS.history} />
          {view.hasInsights && (
            <Tab value="insights" label={t("insights")} panelId={CHAT_PANEL_IDS.insights} />
          )}
        </TabList>
        {/* Beside an icon rail (below 1280 px: an iPad either way, a small laptop)
            Felsökning and Redigera are named icons. */}
        <div className="flex min-w-max flex-1 items-center justify-end gap-2">
          <ClassificationToken name={partner.securityClassification} />
          {debug && (debug.isEnabled || !coarse) && (
            <Button
              label={t("chat_debug_open")}
              variant="secondary"
              icon={<Bug aria-hidden="true" />}
              isIconOnly={compact}
              isDisabled={!debug.isEnabled}
              tooltip={
                debug.isEnabled
                  ? compact
                    ? t("chat_debug_open")
                    : undefined
                  : t("chat_debug_no_turn_title")
              }
              onClick={(event) => debug.onOpen(event.currentTarget)}
            />
          )}
          {editHref && (
            <Button
              label={t("edit")}
              variant="ghost"
              href={editHref}
              icon={compact ? <Pencil aria-hidden="true" /> : undefined}
              isIconOnly={compact}
              tooltip={compact ? t("edit") : undefined}
            />
          )}
          <Button label={t("new_conversation")} variant="primary" onClick={onNewConversation} />
          {menuItems.length > 0 && (
            <MoreMenu label={t("chat_more_options")} items={menuItems} alignment="end" />
          )}
        </div>
      </div>

      {/* On a phone, held either way. It carries the menu button, so the
          shell's top bar gives way to it (OWN_MOBILE_HEADER). */}
      <div
        {...OWN_MOBILE_HEADER}
        className="border-ax-border wide:hidden flex min-h-14 shrink-0 items-center gap-0.5 border-b px-1"
      >
        <AppMenuButton />
        {/* The page's heading, met before the switcher that shows it. */}
        {title !== null && <h1 className="sr-only">{title}</h1>}
        <PartnerSwitcher
          partner={partner}
          items={switcherItems}
          title={title}
          subtitle={subtitle}
          variant="mobile"
        />
        <span aria-hidden="true" className="hidden flex-1 sm:block" />
        <IconButton
          label={t("new_conversation")}
          icon={<SquarePen className="size-5" />}
          variant="ghost"
          onClick={onNewConversation}
          className="size-11"
        />
        <MoreMenu
          label={t("chat_more_options")}
          items={mobileMenu}
          alignment="end"
          presentation="adaptive"
        />
      </div>
      {/* Offline: under the header at every width (the shell's gives way). */}
      <ConnectionBanner />
    </>
  );
}
