"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronRight, FileText, ListChecks, PenLine, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useId, type ReactNode } from "react";
import { EntityAvatar } from "@/components/composites/entity-avatar";
import { iconUrl } from "@/components/composites/icon-field";
import { useAppContext } from "@/components/providers/app-context";
import { chatPartnerHref } from "@/features/assistants/assistants";
import { spaceRouteId } from "@/features/spaces/space";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
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
  tone: string;
};

const STARTERS: Starter[] = [
  { key: "summarize", icon: FileText, tone: "bg-ax-blue-muted text-ax-blue" },
  { key: "draft", icon: PenLine, tone: "bg-ax-purple-muted text-ax-purple" },
  { key: "plan", icon: ListChecks, tone: "bg-ax-teal-muted text-ax-teal" }
];

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
        spaceName: space.name,
        href: chatPartnerHref(spaceRouteId(space), { type: "assistant", id: assistant.id })
      });
      if (result.length === 4) return result;
    }
  }
  return result;
}

function QuickAssistants() {
  const t = useTranslations();
  const headingId = useId();
  const assistants = useQuickAssistants(true);
  if (assistants.length === 0) return null;
  return (
    <section aria-labelledby={headingId} className="flex w-full flex-col gap-2.5">
      <div className="flex items-center justify-between gap-2">
        <h2 id={headingId} className="text-ax-text-secondary text-[13px] font-semibold">
          {t("chat_your_assistants")}
        </h2>
        <Link
          href="/dashboard"
          className="text-ax-text-accent focus-visible:outline-ring rounded-ax-inner inline-flex min-h-6 items-center text-[13px] font-semibold underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11"
        >
          {t("chat_show_all_assistants")}
        </Link>
      </div>
      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {assistants.map((assistant) => (
          <li key={assistant.id}>
            <Link
              href={assistant.href}
              className="border-ax-border hover:bg-ax-hover focus-visible:outline-ring flex min-h-[58px] items-center gap-3 rounded-[0.875rem] border py-2 ps-2.5 pe-3 focus-visible:outline-2 focus-visible:outline-offset-2"
            >
              <EntityAvatar
                id={assistant.id}
                name={assistant.name}
                src={iconUrl(assistant.iconId)}
                size="lg"
                className="size-9"
              />
              <span className="flex min-w-0 flex-1 flex-col leading-tight">
                <span className="truncate font-semibold">{assistant.name}</span>
                <span className="text-ax-text-secondary truncate text-[12.5px]">
                  {assistant.spaceName}
                </span>
              </span>
              <ChevronRight aria-hidden="true" className="text-ax-text-secondary size-4 shrink-0" />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * The empty conversation: a greeting (personal assistant) or the partner's
 * name and description, the composer centred, and for the personal assistant
 * three starter cards (they fill the composer) plus quick links to the user's
 * assistants.
 */
export function StartState({
  partner,
  composer,
  onPickStarter
}: {
  partner: ChatPartner;
  composer: ReactNode;
  onPickStarter: (prompt: string) => void;
}) {
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
    <div className="flex w-full flex-1 flex-col items-center px-4 py-8 sm:py-10">
      <div className="my-auto flex w-full max-w-[720px] flex-col items-center gap-7">
        <div className="flex flex-col items-center gap-2.5 text-center">
          {personal ? (
            <BrandMark className="size-[38px]" />
          ) : (
            <EntityAvatar
              id={partner.id}
              name={partner.name}
              src={iconUrl(partner.iconId)}
              size="xl"
            />
          )}
          <h1 className="mt-1 text-[1.625rem] leading-tight font-semibold tracking-[-0.015em] sm:text-[1.9375rem]">
            {personal
              ? (greeting ?? (
                  <span className="invisible">{t("hi_firstname", { firstName: name })}</span>
                ))
              : partner.name}
          </h1>
          <p className="text-ax-text-secondary max-w-xl text-base">
            {personal
              ? t("chat_start_subtitle")
              : partner.description?.trim() || t("chat_start_ask", { name: partner.name })}
          </p>
        </div>

        {composer}

        {personal && (
          <>
            <ul className="grid w-full grid-cols-1 gap-2.5 sm:grid-cols-3">
              {STARTERS.map((starter) => {
                const text = STARTER_TEXT[starter.key];
                const Icon = starter.icon;
                return (
                  <li key={starter.key} className="flex">
                    <button
                      type="button"
                      onClick={() => onPickStarter(t(text.prompt))}
                      className="border-ax-border hover:bg-ax-hover focus-visible:outline-ring flex w-full items-start gap-3 rounded-[0.875rem] border p-3.5 text-start focus-visible:outline-2 focus-visible:outline-offset-2"
                    >
                      <span
                        aria-hidden="true"
                        className={cn(
                          "rounded-ax-inner flex size-8 shrink-0 items-center justify-center",
                          starter.tone
                        )}
                      >
                        <Icon className="size-4" />
                      </span>
                      <span className="flex flex-col gap-0.5">
                        <span className="font-semibold">{t(text.label)}</span>
                        <span className="text-ax-text-secondary text-[12.5px] leading-snug">
                          {t(text.description)}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
            <QuickAssistants />
          </>
        )}
      </div>
    </div>
  );
}
