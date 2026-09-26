"use client";

import { useSuspenseQuery } from "@tanstack/react-query";
import {
  BookOpen,
  BookOpenCheck,
  ChevronLeft,
  Globe,
  KeyRound,
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
import { ResourceApiKeysSection } from "@/features/api-keys/resource-api-keys-section";
import { useSpace } from "@/features/spaces/use-space";
import { SkillBindingsSection } from "@/features/skills/skill-bindings-section";
import { chatPartnerHref } from "../assistants";
import { AiSection } from "./ai-section";
import { GeneralSection } from "./general-section";
import { AttachmentsSection } from "./attachments-section";
import { CapabilitiesSection } from "./capabilities-section";
import { InstructionsSection } from "./instructions-section";
import { KnowledgeSection } from "./knowledge-section";
import { McpSection } from "./mcp-section";
import { PublishingSection } from "./publishing-section";
import { SecuritySection } from "./security-section";
import { assistantQueryOptions, type Assistant, useUpdateAssistant } from "./use-assistant";

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
  const { space, routeId, can } = useSpace();
  const { data: assistant } = useSuspenseQuery(assistantQueryOptions(browserApi, assistantId));
  const update = useUpdateAssistant(assistantId);

  const chatHref = chatPartnerHref(routeId, { ...assistant, type: "assistant" as const });

  const hasMcp =
    (space.mcp_servers?.length ?? 0) > 0 || assistant.effective_config?.mcp_enforced === true;
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
    ...(can("read", "skill") && (!space.personal || space.default_assistant?.id !== assistant.id)
      ? [
          {
            id: "skills",
            label: t("skills"),
            icon: BookOpenCheck,
            node: (
              <SkillBindingsSection
                resource="assistant"
                resourceId={assistant.id}
                canEdit={permissions.includes("edit")}
                save={(bindings) => update.mutateAsync({ skill_bindings: bindings })}
              />
            )
          }
        ]
      : []),
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
      id: "capabilities",
      label: t("capabilities"),
      icon: Globe,
      node: <CapabilitiesSection assistant={assistant} />
    },
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
    {
      id: "api-keys",
      label: t("api_keys"),
      icon: KeyRound,
      node: (
        <ResourceApiKeysSection
          scopeType="assistant"
          scopeId={assistant.id}
          resourceName={assistant.name}
        />
      )
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
      {/* Edge to edge in the space frame (data-space-full-bleed drops its
          inset), so the header spans the page panel and pins flush to the top
          of the scroll container (main#main-content); the content re-pads
          itself and stays centered. */}
      <div data-space-full-bleed className="flex shrink-0 flex-col">
        <header className="bg-background sticky top-0 z-30 border-b">
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
              className="flex snap-x [scrollbar-width:none] gap-1 overflow-x-auto pb-2 [&::-webkit-scrollbar]:hidden"
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

        {/* The sticky header (about 7 rem) must never cover focus (WCAG
            2.4.11): every element below it, the anchored sections included,
            keeps 8 rem of scroll margin, so Tab, focus() and the section links
            scroll it into view below the header. Scroll padding on the scroll
            container would do the same, but main#main-content is shared by
            every page. */}
        <div className="mx-auto flex w-full max-w-4xl flex-col gap-8 px-6 py-8 [&_*]:scroll-mt-32">
          {sections.map((section) => (
            <div key={section.id} id={section.id}>
              {section.node}
            </div>
          ))}
        </div>
      </div>
    </SaveStatusProvider>
  );
}

export type { Assistant };
