"use client";

import { useSuspenseQuery } from "@tanstack/react-query";
import {
  BookOpen,
  ChevronLeft,
  type LucideIcon,
  MessageSquare,
  Paperclip,
  Play,
  Plug,
  Send,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles
} from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { SaveStatusIndicator, SaveStatusProvider } from "@/components/composites/save-status";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/api/browser";
import { cn } from "@/lib/utils";
import { useSpace } from "@/features/spaces/use-space";
import { chatPartnerHref } from "../assistants";
import { AiSection } from "./ai-section";
import { GeneralSection } from "./general-section";
import { AttachmentsSection } from "./attachments-section";
import { InstructionsSection } from "./instructions-section";
import { KnowledgeSection } from "./knowledge-section";
import { McpSection } from "./mcp-section";
import { PublishingSection } from "./publishing-section";
import { SecuritySection } from "./security-section";
import { assistantQueryOptions, type Assistant } from "./use-assistant";

/** Highlights the section currently in view as the user scrolls. */
function useActiveSection(ids: string[]) {
  const [active, setActive] = useState(ids[0] ?? "");
  const key = ids.join(",");

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActive(visible[0].target.id);
      },
      { rootMargin: "-128px 0px -55% 0px" }
    );
    for (const id of key.split(",")) {
      const element = document.getElementById(id);
      if (element) observer.observe(element);
    }
    return () => observer.disconnect();
  }, [key]);

  return active;
}

/**
 * Assistant settings. Saved per section (web-next pattern; the Svelte app's
 * global draft/diff editor is intentionally not ported). A single full-width
 * column under a sticky header; a horizontal anchor strip (not a second sidebar)
 * navigates the sections, and the header carries the aggregate save state and a
 * shortcut into chat.
 */
export function AssistantEditor({ assistantId }: { assistantId: string }) {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const { data: assistant } = useSuspenseQuery(assistantQueryOptions(browserApi, assistantId));

  const chatHref = chatPartnerHref(routeId, { ...assistant, type: "assistant" as const });

  const hasMcp = (space.mcp_servers?.length ?? 0) > 0;
  const permissions = assistant.permissions ?? [];
  const hasPublishing = permissions.includes("publish") || permissions.includes("insight_toggle");

  const sections: { id: string; label: string; icon: LucideIcon; node: React.ReactNode }[] = [
    {
      id: "general",
      label: t("general"),
      icon: SlidersHorizontal,
      node: <GeneralSection assistant={assistant} />
    },
    {
      id: "instructions",
      label: t("instructions"),
      icon: MessageSquare,
      node: <InstructionsSection assistant={assistant} />
    },
    {
      id: "knowledge",
      label: t("knowledge"),
      icon: BookOpen,
      node: <KnowledgeSection assistant={assistant} />
    },
    ...(hasMcp
      ? [
          {
            id: "mcp",
            label: t("mcp_servers"),
            icon: Plug,
            node: <McpSection assistant={assistant} />
          }
        ]
      : []),
    {
      id: "attachments",
      label: t("attachments"),
      icon: Paperclip,
      node: <AttachmentsSection assistant={assistant} />
    },
    {
      id: "ai",
      label: t("ai_settings"),
      icon: Sparkles,
      node: <AiSection assistant={assistant} />
    },
    {
      id: "security",
      label: t("security_and_privacy"),
      icon: ShieldCheck,
      node: <SecuritySection assistant={assistant} />
    },
    ...(hasPublishing
      ? [
          {
            id: "publishing",
            label: t("publishing"),
            icon: Send,
            node: <PublishingSection assistant={assistant} />
          }
        ]
      : [])
  ];

  const activeId = useActiveSection(sections.map((section) => section.id));

  return (
    <SaveStatusProvider>
      {/* Cancel the space layout's p-6 so the header can sit flush at the scroll
          top and span full width; content re-pads itself and stays centered.
          shrink-0 keeps this taller than the scroll viewport (it's a flex item)
          so the sticky header stays pinned through the whole scroll. */}
      <div className="-m-6 flex shrink-0 flex-col">
        <header className="bg-background sticky -top-6 z-30 border-b">
          <div className="mx-auto w-full max-w-4xl px-6">
            <div className="flex items-center justify-between gap-3 py-3">
              <div className="flex min-w-0 items-center gap-2">
                <Link
                  href={`/spaces/${routeId}/assistants`}
                  aria-label={t("assistants")}
                  className="text-muted-foreground hover:text-foreground"
                >
                  <ChevronLeft className="size-5" />
                </Link>
                <span className="text-muted-foreground hidden text-sm sm:inline">
                  {t("assistants")}
                </span>
                <span className="text-muted-foreground hidden sm:inline">/</span>
                <h1 className="truncate text-base font-semibold">{assistant.name}</h1>
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <span className="hidden md:inline">
                  <SaveStatusIndicator />
                </span>
                <Button asChild size="sm">
                  <Link href={chatHref}>
                    <Play className="size-4" />
                    {t("test")}
                  </Link>
                </Button>
              </div>
            </div>
            <nav
              aria-label={t("settings")}
              className="flex snap-x gap-1 overflow-x-auto pb-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
            >
              {sections.map((section) => (
                <a
                  key={section.id}
                  href={`#${section.id}`}
                  aria-current={activeId === section.id ? "true" : undefined}
                  className={cn(
                    "inline-flex snap-start items-center gap-1.5 rounded-md px-3 py-1.5 text-sm whitespace-nowrap transition-colors",
                    activeId === section.id
                      ? "bg-muted text-foreground font-medium"
                      : "text-muted-foreground hover:text-foreground hover:bg-muted/60"
                  )}
                >
                  <section.icon aria-hidden="true" className="size-4 shrink-0" />
                  {section.label}
                </a>
              ))}
            </nav>
          </div>
        </header>

        <div className="mx-auto flex w-full max-w-4xl flex-col gap-8 px-6 py-8">
          {sections.map((section) => (
            <div key={section.id} id={section.id} className="scroll-mt-28">
              {section.node}
            </div>
          ))}
        </div>
      </div>
    </SaveStatusProvider>
  );
}

export type { Assistant };
