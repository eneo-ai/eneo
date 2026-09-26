"use client";

import { IconButton } from "@astryxdesign/core/IconButton";
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Check, ChevronDown, History, Menu, ShieldCheck, SquarePen } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { EntityAvatar } from "@/components/composites/entity-avatar";
import { iconUrl } from "@/components/composites/icon-field";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { OPEN_NAV_EVENT } from "@/components/shell/routes";
import type { ChatPartner } from "@/lib/chat/types";
import { cn } from "@/lib/utils";
import type { ChatPartnerSwitcherItem } from "./partner-switcher";
import { BrandMark } from "./start-state";

/** Asks the app shell to open its navigation drawer (phones). */
function openAppNavigation() {
  window.dispatchEvent(new CustomEvent(OPEN_NAV_EVENT));
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
      <>
        <PartnerTile partner={partner} size="sm" />
        <span className="truncate">{partner.name}</span>
        {chevron}
      </>
    );
  }
  return (
    <>
      <PartnerTile partner={partner} size="md" />
      <span className="flex min-w-0 flex-col items-start leading-tight">
        <span className="max-w-full truncate font-semibold">{partner.name}</span>
        {subtitle && (
          <span className="text-ax-text-secondary max-w-full truncate text-xs">{subtitle}</span>
        )}
      </span>
      {chevron}
    </>
  );
}

const SWITCHER_CLASS: Record<SwitcherVariant, string> = {
  header:
    "flex h-[42px] max-w-[min(22rem,40vw)] min-w-0 items-center gap-2.5 rounded-ax-element ps-1.5 pe-2 text-start",
  token:
    "border-ax-border-control flex h-8 max-w-[16rem] min-w-0 items-center gap-1.5 rounded-full border ps-1 pe-2 text-[13px] font-semibold pointer-coarse:h-11",
  mobile:
    "flex min-h-11 min-w-0 flex-1 flex-col items-center justify-center rounded-ax-container px-2"
};

/**
 * The assistant selector: shows who you are talking to and, in a space,
 * opens today's partner switcher (assistants and group chats of the space).
 * Without switcher items it is a static identity.
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
  const interactive = (items?.length ?? 0) > 1;

  if (!interactive) {
    return (
      <div className={cn(SWITCHER_CLASS[variant], variant === "token" && "border-transparent")}>
        <SwitcherFace partner={partner} subtitle={subtitle} variant={variant} interactive={false} />
      </div>
    );
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className={cn(
            SWITCHER_CLASS[variant],
            "hover:bg-ax-hover focus-visible:outline-ring data-[state=open]:bg-ax-hover focus-visible:outline-2 focus-visible:outline-offset-2"
          )}
        >
          <span className="sr-only">{t("chat_switch_assistant")}: </span>
          <SwitcherFace partner={partner} subtitle={subtitle} variant={variant} interactive />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align={variant === "mobile" ? "center" : "start"} className="w-72">
        <DropdownMenuLabel>{t("select_an_assistant")}</DropdownMenuLabel>
        {items!.map((item) => (
          <DropdownMenuItem key={`${item.type}:${item.id}`} asChild>
            <Link
              href={item.href}
              aria-current={item.active ? "page" : undefined}
              className="flex min-w-0 items-center gap-2"
            >
              <PartnerTile
                partner={{
                  id: item.id,
                  name: item.name,
                  iconId: item.iconId ?? null,
                  type: item.type === "default-assistant" ? "default-assistant" : "assistant"
                }}
                size="sm"
              />
              <span className="min-w-0 flex-1 truncate">{item.name}</span>
              {item.active && <Check aria-hidden="true" className="text-ax-text-accent size-4" />}
            </Link>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
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
  /** Conversation title (the page's h1); null in the start state, whose greeting is the h1. */
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
        <IconButton
          label={t("chat_open_menu")}
          icon={<Menu className="size-5" />}
          variant="ghost"
          onClick={openAppNavigation}
          className="size-11"
        />
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
