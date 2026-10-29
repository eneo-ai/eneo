"use client";

import {
  DropdownMenu,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem
} from "@astryxdesign/core/DropdownMenu";
import { IconButton } from "@astryxdesign/core/IconButton";
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { ChevronDown, History, Menu, SquarePen } from "lucide-react";
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
 * The phone switcher's accessible name (decision 2): what its two lines show,
 * with the space they leave out for room, then what it does. "Upphandlings-
 * analys mot LOU. Upphandlingsassistenten i Upphandling, säkerhetsklass
 * Intern. Byt assistent"
 */
function phoneSwitcherName(
  t: ReturnType<typeof useTranslations>,
  partner: ChatPartner,
  title: string | null
): string {
  const name = displayPartnerName(partner, t);
  const space = partnerSpace(partner);
  const who = [
    space ? t("chat_header_in_space", { assistant: name, space }) : name,
    partner.securityClassification
      ? t("chat_header_classified", { classification: partner.securityClassification })
      : null
  ]
    .filter(Boolean)
    .join(", ");
  return [title, who]
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
          </span>
          {(space || partner.securityClassification) && (
            <span className={second}>
              {space && <span className="truncate">{space}</span>}
              {classification}
            </span>
          )}
        </span>
      );
    }
    return (
      <span className="flex min-w-0 flex-col items-start text-start">
        <span className="max-w-full truncate text-[1.0625rem] leading-snug font-semibold">
          {title}
        </span>
        <span className={second}>
          <span className="flex min-w-0 items-center gap-0.5">
            <span className="truncate">{name}</span>
            {/* Left out for room at 390px; the switcher's name and its menu say it. */}
            {space && <span className="sr-only">, {space}</span>}
            {chevron}
          </span>
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
        <span className="max-w-full truncate font-semibold">{name}</span>
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
    "text-ax-text border-ax-border-control flex h-8 max-w-[16rem] min-w-0 items-center justify-start rounded-full border ps-1 pe-2 text-[13px] font-semibold pointer-coarse:h-11",
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
        label:
          variant === "mobile"
            ? phoneSwitcherName(t, partner, title)
            : t("chat_switch_assistant_named", { name: displayPartnerName(partner, t) }),
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

export type HeaderMenuItem = {
  label: string;
  onClick: () => void;
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
  view?: { value: "chat" | "insights"; onChange: (value: "chat" | "insights") => void } | null;
  historyOpen: boolean;
  onToggleHistory: () => void;
  onNewConversation: () => void;
  /** Session actions (rename, delete) and partner actions (edit). */
  menuItems: HeaderMenuItem[];
  /** Personal assistant start state: the selector lives in the composer instead. */
  minimal?: boolean;
};

/** Opens the partner's conversation list; named after what it opens, with aria-expanded for the state. */
function HistoryButton({
  partner,
  open,
  onToggle
}: {
  partner: ChatPartner;
  open: boolean;
  onToggle: () => void;
}) {
  const t = useTranslations();
  const label = t("chat_history_with", { name: displayPartnerName(partner, t) });
  return (
    <IconButton
      label={label}
      tooltip={label}
      icon={<History className="size-[18px]" />}
      variant="ghost"
      aria-expanded={open}
      aria-controls={open ? "chat-history" : undefined}
      onClick={onToggle}
      className={cn(open && "bg-ax-selected")}
    />
  );
}

/**
 * Chat header. From 1024px (56px): assistant selector, divider,
 * conversation title (h1), the space's security classification, the
 * Chatt/Insikter switch, new conversation, history and a menu for session
 * actions. Below 1024px (decision 2): the app menu (opens the shell's
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
  minimal = false
}: ChatHeaderProps) {
  const t = useTranslations();
  const subtitle = [partner.spaceName, modelName].filter(Boolean).join(" · ") || null;
  const mobileMenu: HeaderMenuItem[] = [
    {
      label: historyOpen
        ? t("chat_history_close")
        : t("chat_history_with", { name: displayPartnerName(partner, t) }),
      onClick: onToggleHistory
    },
    ...(view
      ? [
          {
            label: view.value === "chat" ? t("insights") : t("chat"),
            onClick: () => view.onChange(view.value === "chat" ? "insights" : "chat")
          }
        ]
      : []),
    ...menuItems
  ];

  return (
    <>
      {/* From 1024px, beside the SideNav */}
      <div className="border-ax-border hidden min-h-14 shrink-0 items-center gap-3 border-b ps-2.5 pe-3 lg:flex">
        {!minimal && (
          <>
            <PartnerSwitcher
              partner={partner}
              items={switcherItems}
              subtitle={subtitle}
              variant="header"
            />
            {title !== null && (
              <span aria-hidden="true" className="bg-ax-border-strong h-[22px] w-px shrink-0" />
            )}
          </>
        )}
        {title !== null ? (
          <h1 className="text-ax-text-secondary min-w-0 flex-1 truncate text-sm font-medium">
            {title}
          </h1>
        ) : (
          <span className="flex-1" />
        )}
        <ClassificationToken name={partner.securityClassification} />
        {view && (
          <SegmentedControl
            label={t("chat_view_label")}
            value={view.value}
            onChange={(value) => view.onChange(value === "insights" ? "insights" : "chat")}
            size="sm"
          >
            <SegmentedControlItem value="chat" label={t("chat")} />
            <SegmentedControlItem value="insights" label={t("insights")} />
          </SegmentedControl>
        )}
        <div className="flex shrink-0 items-center gap-1">
          <IconButton
            label={t("new_conversation")}
            tooltip={t("new_conversation")}
            icon={<SquarePen className="size-[18px]" />}
            variant="ghost"
            onClick={onNewConversation}
          />
          <HistoryButton partner={partner} open={historyOpen} onToggle={onToggleHistory} />
          {menuItems.length > 0 && (
            <MoreMenu label={t("chat_more_options")} items={menuItems} alignment="end" />
          )}
        </div>
      </div>

      {/* Below 1024px. It carries the menu button, so the shell's top bar
          gives way to it (OWN_MOBILE_HEADER). */}
      <div
        {...OWN_MOBILE_HEADER}
        className="border-ax-border flex min-h-14 shrink-0 items-center gap-0.5 border-b px-1 lg:hidden"
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
          className="size-11"
        />
      </div>
      {/* Offline: under the header at every width (the shell's gives way). */}
      <ConnectionBanner />
    </>
  );
}
