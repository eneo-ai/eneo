"use client";

import {
  DropdownMenu,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem
} from "@astryxdesign/core/DropdownMenu";
import { IconButton } from "@astryxdesign/core/IconButton";
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { ChevronDown, History, Menu, ShieldCheck, SquarePen } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { EntityAvatar } from "@/components/composites/entity-avatar";
import { iconUrl } from "@/components/composites/icon-field";
import { OPEN_NAV_EVENT } from "@/components/shell/routes";
import { useOwnMobileHeader } from "@/components/shell/shell-context";
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
  partner: Pick<ChatPartner, "id" | "name" | "iconId" | "type">;
  size: "sm" | "md";
}) {
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
      name={partner.name}
      src={iconUrl(partner.iconId)}
      size={size === "md" ? "md" : "sm"}
      className={size === "md" ? "size-[30px] rounded-[9px]" : "rounded-full"}
    />
  );
}

function SwitcherFace({
  partner,
  subtitle,
  variant,
  interactive
}: {
  partner: ChatPartner;
  subtitle: string | null;
  variant: SwitcherVariant;
  interactive: boolean;
}) {
  const chevron = interactive && (
    <ChevronDown aria-hidden="true" className="text-ax-text-secondary size-4 shrink-0" />
  );
  if (variant === "mobile") {
    return (
      <span className="flex min-w-0 flex-col items-center leading-tight">
        <span className="flex max-w-full min-w-0 items-center gap-1 text-[15px] font-semibold">
          <span className="truncate">{partner.name}</span>
          {chevron}
        </span>
        {subtitle && (
          <span className="text-ax-text-secondary max-w-full truncate text-xs">{subtitle}</span>
        )}
      </span>
    );
  }
  if (variant === "token") {
    return (
      <span className="flex min-w-0 items-center gap-1.5">
        <PartnerTile partner={partner} size="sm" />
        <span className="truncate">{partner.name}</span>
        {chevron}
      </span>
    );
  }
  return (
    <span className="flex min-w-0 items-center gap-2.5">
      <PartnerTile partner={partner} size="md" />
      <span className="flex min-w-0 flex-col items-start leading-tight">
        <span className="max-w-full truncate font-semibold">{partner.name}</span>
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
  mobile:
    "text-ax-text flex h-auto min-h-11 min-w-0 flex-1 flex-col items-center justify-center rounded-ax-container px-2"
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
  subtitle,
  variant
}: {
  partner: ChatPartner;
  items?: ChatPartnerSwitcherItem[];
  subtitle: string | null;
  variant: SwitcherVariant;
}) {
  const t = useTranslations();
  const router = useRouter();
  const interactive = (items?.length ?? 0) > 1;

  if (!interactive) {
    return (
      <div className={cn(SWITCHER_CLASS[variant], variant === "token" && "border-transparent")}>
        <SwitcherFace partner={partner} subtitle={subtitle} variant={variant} interactive={false} />
      </div>
    );
  }

  const active = items!.find((item) => item.active);
  return (
    <DropdownMenu
      button={{
        label: t("chat_switch_assistant_named", { name: partner.name }),
        variant: "ghost",
        className: SWITCHER_CLASS[variant],
        children: (
          <SwitcherFace partner={partner} subtitle={subtitle} variant={variant} interactive />
        )
      }}
      // The face draws its own chevron (beside the name on phones).
      hasChevron={false}
      alignment={variant === "mobile" ? "center" : "start"}
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
            label={item.name}
            icon={
              <PartnerTile
                partner={{
                  id: item.id,
                  name: item.name,
                  iconId: item.iconId ?? null,
                  type: item.type === "default-assistant" ? "default-assistant" : "assistant"
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

function HistoryButton({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  const t = useTranslations();
  return (
    <IconButton
      label={t("history")}
      tooltip={t("history")}
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
 * Chat header. Desktop (≥768px, 56px): assistant selector, divider,
 * conversation title (h1), the space's security classification, the
 * Chatt/Insikter switch, new conversation, history and a menu for session
 * actions. Phones: the app menu (opens the shell's drawer), the selector
 * centred with "space · model", new conversation and the same menu.
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
  // The chat header carries the phone menu button, so the shell hides its own
  // top bar while this header is mounted.
  useOwnMobileHeader();
  const t = useTranslations();
  const subtitle = [partner.spaceName, modelName].filter(Boolean).join(" · ") || null;
  const mobileMenu: HeaderMenuItem[] = [
    { label: historyOpen ? t("chat_history_close") : t("history"), onClick: onToggleHistory },
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
      {/* Desktop and tablet */}
      <div className="border-ax-border hidden min-h-14 shrink-0 items-center gap-3 border-b ps-2.5 pe-3 md:flex">
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
        {partner.securityClassification && (
          <span className="bg-ax-muted text-ax-text-secondary flex h-[26px] shrink-0 items-center gap-1.5 rounded-full ps-2 pe-2.5 text-xs font-semibold">
            <ShieldCheck aria-hidden="true" className="size-3.5" />
            <span className="sr-only">{t("chat_security_classification")}: </span>
            {partner.securityClassification}
          </span>
        )}
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
          <HistoryButton open={historyOpen} onToggle={onToggleHistory} />
          {menuItems.length > 0 && (
            <MoreMenu label={t("chat_more_options")} items={menuItems} alignment="end" />
          )}
        </div>
      </div>

      {/* Phones: the shell hides its own top bar on chat routes. */}
      <div className="border-ax-border flex min-h-14 shrink-0 items-center gap-0.5 border-b px-1 md:hidden">
        <AppMenuButton />
        <PartnerSwitcher
          partner={partner}
          items={switcherItems}
          subtitle={subtitle}
          variant="mobile"
        />
        {title !== null && <h1 className="sr-only">{title}</h1>}
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
    </>
  );
}
