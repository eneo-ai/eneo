"use client";

import { List, ListItem } from "@astryxdesign/core/List";
import { useQuery } from "@tanstack/react-query";
import { FileText, ListChecks, PenLine, type LucideIcon } from "lucide-react";
import Link from "@/lib/link";
import { useTranslations } from "use-intl";
import { useId, type ReactNode } from "react";
import { EntityAvatar } from "@/components/composites/entity-avatar";
import { iconUrl } from "@/components/composites/icon-field";
import { useAppContext } from "@/components/providers/app-context";
import { chatPartnerHref } from "@/features/assistants/assistants";
import { spaceRouteId } from "@/features/spaces/space";
import { spaceDisplayName } from "@/features/spaces/space-name";
import { WhatsNewBanner } from "@/features/whats-new/release-banner";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { displayPartnerName } from "@/lib/chat/partner-name";
import type { ChatPartner } from "@/lib/chat/types";
import { cn } from "@/lib/utils";
import { firstNameOf, greetingFor } from "./format";
import { useNow } from "./use-now";

// The Eneo mark, decorative here (the greeting is the heading).
const MARK_PATH =
  "M58.907 25.2079C92.3974 -8.28227 146.632 -7.74821 180.04 25.6601C213.448 59.0684 213.981 113.302 180.491 146.792C147.001 180.282 92.7675 179.749 59.3591 146.341L42.3884 129.37L102.728 69.0302C112.101 59.6577 127.297 59.6577 136.67 69.0302C146.042 78.4027 146.042 93.5982 136.67 102.971L116.21 123.431C127.132 124.616 138.361 121.04 146.55 112.852C160.964 98.4371 161.094 74.5971 146.098 59.6015C131.103 44.6059 107.262 44.7349 92.8474 59.1493L75.8767 76.1191L41.9362 42.1786L58.907 25.2079ZM66.3328 85.7548L32.5876 119.5L1.67155 88.583C0.109466 87.0209 0.109504 84.4888 1.67155 82.9267L32.5876 52.0097L66.3328 85.7548Z";

export function BrandMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 -21 214 214"
      aria-hidden="true"
      className={cn("text-ax-text-accent", className)}
    >
      <path d={MARK_PATH} fill="currentColor" />
    </svg>
  );
}

type Starter = {
  key: "summarize" | "draft" | "plan";
  icon: LucideIcon;
};

const STARTERS: Starter[] = [
  { key: "summarize", icon: FileText },
  { key: "draft", icon: PenLine },
  { key: "plan", icon: ListChecks }
];

/** Section headings of the start state: 18 px, in a 44 px row so "Visa alla" beside one is a full target. */
const SECTION_HEADING = "text-lg leading-tight font-semibold text-balance";

const STARTER_TEXT = {
  summarize: {
    label: "personal_assistant_suggestion_summarize",
    description: "chat_starter_summarize_description",
    prompt: "personal_assistant_prompt_summarize"
  },
  draft: {
    label: "personal_assistant_suggestion_draft",
    description: "chat_starter_draft_description",
    prompt: "personal_assistant_prompt_draft"
  },
  plan: {
    label: "personal_assistant_suggestion_plan",
    description: "chat_starter_plan_description",
    prompt: "personal_assistant_prompt_plan"
  }
} as const;

type QuickAssistant = {
  id: string;
  name: string;
  iconId: string | null;
  spaceName: string;
  href: string;
};

/** Up to four assistants from the user's shared spaces (the dashboard query, shared cache). */
function useQuickAssistants(enabled: boolean): QuickAssistant[] {
  const t = useTranslations();
  const { data } = useQuery({
    queryKey: ["dashboard"],
    enabled,
    queryFn: () => unwrap(browserApi.GET("/api/v1/dashboard/"))
  });
  if (!data) return [];
  const result: QuickAssistant[] = [];
  for (const space of data.spaces.items) {
    if (space.personal) continue;
    for (const assistant of space.applications?.assistants.items ?? []) {
      result.push({
        id: assistant.id,
        name: assistant.name,
        iconId: assistant.icon_id ?? null,
        spaceName: spaceDisplayName(space, t),
        href: chatPartnerHref(spaceRouteId(space), { type: "assistant", id: assistant.id })
      });
      if (result.length === 4) return result;
    }
  }
  return result;
}

/**
 * "Prova att fråga": the three starters as rows (decision 8). Tapping one
 * fills the composer with its prompt; the icon takes the same 36 px slot as
 * an assistant's tile, so both lists start their text on one line.
 */
function Starters({ onPick }: { onPick: (prompt: string) => void }) {
  const t = useTranslations();
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="flex w-full flex-col">
      <div className="flex min-h-11 items-center">
        <h2 id={headingId} className={SECTION_HEADING}>
          {t("chat_try_asking")}
        </h2>
      </div>
      <List hasDividers edgeCompensation="inline">
        {STARTERS.map((starter) => {
          const text = STARTER_TEXT[starter.key];
          const Icon = starter.icon;
          return (
            <ListItem
              key={starter.key}
              label={t(text.label)}
              description={t(text.description)}
              onClick={() => onPick(t(text.prompt))}
              startContent={
                <span className="flex size-9 shrink-0 items-center justify-center">
                  <Icon aria-hidden="true" className="text-ax-text-secondary size-5" />
                </span>
              }
            />
          );
        })}
      </List>
    </section>
  );
}

/**
 * "Dina assistenter": up to four of the user's assistants with their space,
 * and "Visa alla" to the catalog. A row opens a chat, so no chevron (as in
 * the catalog and the switcher).
 */
function QuickAssistants() {
  const t = useTranslations();
  const headingId = useId();
  const assistants = useQuickAssistants(true);
  if (assistants.length === 0) return null;
  return (
    <section aria-labelledby={headingId} className="flex w-full flex-col">
      <div className="flex min-h-11 items-center justify-between gap-2">
        <h2 id={headingId} className={SECTION_HEADING}>
          {t("chat_your_assistants")}
        </h2>
        <Link
          href="/dashboard"
          className="text-ax-text-accent focus-visible:outline-ring rounded-ax-inner -me-2 inline-flex min-h-11 items-center px-2 text-sm font-semibold underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:-outline-offset-2"
        >
          {t("chat_show_all_assistants")}
        </Link>
      </div>
      <List hasDividers edgeCompensation="inline">
        {assistants.map((assistant) => (
          <ListItem
            key={assistant.id}
            href={assistant.href}
            label={assistant.name}
            description={assistant.spaceName}
            startContent={
              <EntityAvatar
                id={assistant.id}
                name={assistant.name}
                src={iconUrl(assistant.iconId)}
                size="lg"
                className="size-9"
              />
            }
          />
        ))}
      </List>
    </section>
  );
}

/**
 * The empty conversation: a greeting (personal assistant) or the partner's
 * name and description; the composer, centred under it from 640px (on phones
 * the view docks it at the bottom, where it stays: decision 5); and for the
 * personal assistant "Prova att fråga" and "Dina assistenter" (decision 8),
 * side by side where the column is wide enough.
 */
export type StartHeadingLevel = 1 | 2 | 3;

const START_HEADINGS = { 1: "h1", 2: "h2", 3: "h3" } as const;

export function StartState({
  partner,
  composer,
  onPickStarter,
  headingLevel = 1
}: {
  partner: ChatPartner;
  /** The centred composer; absent on phones, where the view docks it. */
  composer?: ReactNode;
  onPickStarter: (prompt: string) => void;
  /** 1 on a chat page; lower inside a page that has its own h1. */
  headingLevel?: StartHeadingLevel;
}) {
  const StartHeading = START_HEADINGS[headingLevel];
  const t = useTranslations();
  const { user } = useAppContext();
  const now = useNow();
  const personal = partner.type === "default-assistant";
  const name = firstNameOf(user);
  const greeting =
    now === null ? null : t(`chat_greeting_${greetingFor(new Date(now).getHours())}`, { name });

  return (
    // Auto margins centre the content vertically but, unlike justify-center,
    // never push it above the scroll edge when it is taller (zoom, short phones).
    // The personal start leads with its greeting on a phone, start-aligned
    // above its lists; another assistant's has only its introduction, centred
    // at every width.
    <div className="flex w-full flex-1 flex-col items-center px-4 pt-6 pb-4 sm:py-10">
      <div
        className={cn(
          "@container flex w-full max-w-[720px] flex-col gap-7 sm:gap-8",
          personal ? "sm:my-auto sm:items-center" : "my-auto items-center"
        )}
      >
        <div
          className={cn(
            "flex flex-col gap-2.5",
            personal ? "sm:items-center sm:text-center" : "items-center text-center"
          )}
        >
          {personal ? (
            // The mark only where there is room; on a phone the greeting leads.
            <BrandMark className="size-[38px] max-sm:hidden" />
          ) : (
            <EntityAvatar
              id={partner.id}
              name={displayPartnerName(partner, t)}
              src={iconUrl(partner.iconId)}
              size="xl"
            />
          )}
          <StartHeading className="text-[1.625rem] leading-tight font-semibold tracking-[-0.015em] text-balance sm:mt-1 sm:text-[1.9375rem]">
            {personal
              ? (greeting ?? (
                  <span className="invisible">{t("hi_firstname", { firstName: name })}</span>
                ))
              : displayPartnerName(partner, t)}
          </StartHeading>
          <p className="text-ax-text-secondary max-w-xl text-base">
            {personal
              ? t("chat_start_subtitle")
              : partner.description?.trim() ||
                t("chat_start_ask", { name: displayPartnerName(partner, t) })}
          </p>
        </div>

        {/* The one-time release notice sits above the composer (from 640px; on
            phones above the lists, the composer docked under them), never over it. */}
        {personal && <WhatsNewBanner />}
        {composer}

        {personal && (
          // Side by side where the column has room for both (not the window: a
          // side panel narrows it); a lone section (no assistants yet) takes the width.
          <div className="grid w-full grid-cols-1 gap-x-6 gap-y-6 @2xl:grid-cols-2 @2xl:[&>:only-child]:col-span-2">
            <Starters onPick={onPickStarter} />
            <QuickAssistants />
          </div>
        )}
      </div>
    </div>
  );
}
